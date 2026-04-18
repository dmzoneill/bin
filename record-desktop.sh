#!/usr/bin/env python3
"""
Desktop recording using Intel Arc VA-API with XDG Desktop Portal.
Triggers the screen selection dialog and records to MP4.
"""

import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Xdp', '1.0')
from gi.repository import GLib, Gst, Xdp

# Initialize GStreamer
Gst.init(None)


class DesktopRecorder:
    def __init__(self):
        self.output_dir = Path.home() / "Recordings"
        self.output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = self.output_dir / f"desktop_{timestamp}.mp4"

        self.pipeline = None
        self.loop = None
        self.portal = Xdp.Portal()
        self.session = None
        self.stopping = False
        self.recording_started = False
        self.audio_process = None

        # Kill any stale pw-record processes from previous runs
        import subprocess
        subprocess.run(['pkill', '-f', 'pw-record'], capture_output=True)

        # Get the default audio sink name for desktop audio capture
        result = subprocess.run(['pactl', 'get-default-sink'],
                              capture_output=True, text=True)
        self.audio_sink = result.stdout.strip()

    def on_screencast_created(self, portal, result, user_data):
        """Called when screencast session is created."""
        try:
            self.session = portal.create_screencast_session_finish(result)

            # Request screen selection - start triggers the dialog
            self.session.start(
                None,  # parent window
                None,  # cancellable
                self.on_screencast_started,
                None,  # user_data
            )
        except Exception as e:
            print(f"Failed to create session: {e}", file=sys.stderr)
            self.loop.quit()

    def on_screencast_started(self, session, result, user_data):
        """Called when user selects a screen."""
        try:
            success = session.start_finish(result)
            if not success:
                print("Screen selection cancelled", file=sys.stderr)
                self.loop.quit()
                return

            # Get the PipeWire node ID from the variant
            # Format is a(ua{sv}) - array of (node_id, properties_dict)
            streams_variant = session.get_streams()
            if not streams_variant or streams_variant.n_children() == 0:
                print("No streams available", file=sys.stderr)
                self.loop.quit()
                return

            # Get first stream tuple, then get the node_id (first element)
            first_stream = streams_variant.get_child_value(0)
            pw_node_id = first_stream.get_child_value(0).get_uint32()
            print(f"Capturing PipeWire node: {pw_node_id}")

            self.start_recording(pw_node_id)

        except Exception as e:
            print(f"Failed to start screencast: {e}", file=sys.stderr)
            self.loop.quit()

    def start_recording(self, pw_node_id):
        """Build and start the GStreamer pipeline."""
        import subprocess

        # Start pw-record subprocess for desktop audio capture
        # pw-record outputs raw audio to stdout, which we pipe into GStreamer
        self.audio_process = subprocess.Popen(
            ['pw-record', '--target', self.audio_sink,
             '--format', 's16', '--rate', '48000', '--channels', '2',
             '-'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        audio_fd = self.audio_process.stdout.fileno()

        # Pipeline with portal screen source and pw-record audio
        pipeline_str = f"""
            pipewiresrc path={pw_node_id} do-timestamp=true keepalive-time=1000
            ! queue max-size-buffers=30 max-size-time=1000000000 max-size-bytes=0 leaky=downstream
            ! videorate skip-to-first=true
            ! videoconvert n-threads=4
            ! video/x-raw,format=NV12
            ! vah264enc
                rate-control=cqp
                qpi=20 qpp=23 qpb=25
                ref-frames=3
                b-frames=0
                key-int-max=60
            ! h264parse
            ! queue max-size-buffers=30 max-size-time=1000000000
            ! mux.

            fdsrc fd={audio_fd} blocksize=4096
            ! rawaudioparse use-sink-caps=false format=pcm pcm-format=s16le sample-rate=48000 num-channels=2
            ! queue max-size-buffers=100 max-size-time=1000000000 max-size-bytes=0
            ! audioconvert
            ! avenc_aac bitrate=192000
            ! aacparse
            ! queue max-size-buffers=100 max-size-time=1000000000
            ! mux.

            mp4mux name=mux faststart=true
            ! filesink location="{self.output_file}"
        """

        print(f"Recording to: {self.output_file}")
        print("Starting pipeline... please wait...")
        print()

        self.pipeline = Gst.parse_launch(pipeline_str)

        # Watch for messages
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

        # Start playing
        self.pipeline.set_state(Gst.State.PLAYING)

    def on_bus_message(self, bus, message):
        """Handle GStreamer bus messages."""
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Error: {err.message}", file=sys.stderr)
            print(f"Debug: {debug}", file=sys.stderr)
            self.stop()
        elif t == Gst.MessageType.EOS:
            print("EOS received, finalizing...")
            self.finish()
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, pending = message.parse_state_changed()
                if new == Gst.State.PLAYING and not self.recording_started:
                    self.recording_started = True
                    print("Recording started! Press Ctrl+C to stop.")

    def stop(self):
        """Stop recording gracefully."""
        if self.stopping:
            return GLib.SOURCE_REMOVE

        if not self.recording_started:
            print("\nWaiting for recording to start before stopping...")
            # Try again in 500ms
            GLib.timeout_add(500, self.stop)
            return GLib.SOURCE_REMOVE

        self.stopping = True
        print("\nStopping recording...")
        if self.pipeline:
            # Send EOS and wait for it to propagate through the pipeline
            self.pipeline.send_event(Gst.Event.new_eos())
            # Timeout in case EOS doesn't arrive
            GLib.timeout_add_seconds(5, self.force_finish)
            # Don't quit yet - wait for EOS message in on_bus_message
        else:
            self.finish()
        return GLib.SOURCE_REMOVE

    def force_finish(self):
        """Force finish if EOS times out."""
        if not self.stopping:
            return GLib.SOURCE_REMOVE
        print("EOS timeout, forcing shutdown...")
        self.finish()
        return GLib.SOURCE_REMOVE

    def finish(self):
        """Clean up after EOS received."""
        # Stop audio capture first
        if self.audio_process:
            self.audio_process.terminate()
            try:
                self.audio_process.wait(timeout=2)
            except:
                self.audio_process.kill()

        if self.pipeline:
            # Wait for pipeline to finish processing
            self.pipeline.set_state(Gst.State.PAUSED)
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)

        if self.session:
            self.session.close()

        # Check file size
        import os
        try:
            size = os.path.getsize(self.output_file)
            print(f"Saved: {self.output_file} ({size / 1024 / 1024:.1f} MB)")
        except:
            print(f"Saved: {self.output_file}")

        if self.loop:
            self.loop.quit()

    def run(self):
        """Main entry point."""
        print("=== Intel Arc Desktop Recording ===")
        print(f"Output: {self.output_file}")
        print(f"Audio: {self.audio_sink} (desktop audio via pw-record)")
        print()

        self.loop = GLib.MainLoop()

        # Handle Ctrl+C using GLib (works better with main loop)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self.stop)

        # Request screencast session (triggers dialog)
        self.portal.create_screencast_session(
            Xdp.OutputType.MONITOR,
            Xdp.ScreencastFlags.NONE,
            Xdp.CursorMode.EMBEDDED,
            Xdp.PersistMode.NONE,
            None,  # restore token
            None,  # cancellable
            self.on_screencast_created,
            None,  # user_data
        )

        self.loop.run()


if __name__ == "__main__":
    recorder = DesktopRecorder()
    recorder.run()
