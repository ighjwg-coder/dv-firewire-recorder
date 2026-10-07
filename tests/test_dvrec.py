import tempfile
import threading
import unittest
from pathlib import Path

from dvrec.devices import list_devices, find_cameras
from dvrec.recorder import Recorder, RecordConfig, build_command
from dvrec.status import RecorderState, apply_line

FAKE = str(Path(__file__).with_name("fake_dvgrab.py"))


def make_sysfs(root: Path) -> Path:
    devs = root / "devices"
    local = devs / "fw0"
    local.mkdir(parents=True)
    (local / "guid").write_text("0x001106000000abcd\n")
    (local / "is_local").write_text("1\n")
    (local / "vendor_name").write_text("Texas Instruments\n")
    cam = devs / "fw1"
    cam.mkdir()
    (cam / "guid").write_text("0x080046010203abcd\n")
    (cam / "is_local").write_text("0\n")
    (cam / "vendor_name").write_text("SONY\n")
    (cam / "model_name").write_text("DCR-VX2100\n")
    (cam / "units").write_text("0x00a02d:0x010001\n")
    (devs / "fw1.0").mkdir()
    return devs


class DeviceTests(unittest.TestCase):
    def test_lists_controller_and_camera(self):
        with tempfile.TemporaryDirectory() as d:
            devs = make_sysfs(Path(d))
            nodes = {x.node: x for x in list_devices(devs)}
            self.assertEqual(set(nodes), {"fw0", "fw1"})
            self.assertTrue(nodes["fw0"].is_local)
            self.assertFalse(nodes["fw0"].is_avc)
            cams = find_cameras(devs)
            self.assertEqual([c.node for c in cams], ["fw1"])
            self.assertEqual(cams[0].guid, "080046010203abcd")
            self.assertEqual(cams[0].label, "SONY DCR-VX2100")

    def test_missing_sysfs(self):
        self.assertEqual(list_devices(Path("/nonexistent/fw")), [])


class CommandTests(unittest.TestCase):
    def test_tapeless_dv(self):
        cmd = build_command(RecordConfig(), Path("/x/clip-"))
        self.assertEqual(cmd[0], "dvgrab")
        for flag in ("-r", "-a", "-noavc", "-timesys", "-showstatus"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("-format") + 1], "raw")
        self.assertEqual(cmd[-1], "/x/clip-")

    def test_continuous_avi_camera_time_guid(self):
        cfg = RecordConfig(mode="continuous", format="avi", name_time="camera", guid="abc")
        cmd = build_command(cfg, Path("/x/c-"))
        self.assertNotIn("-r", cmd)
        self.assertNotIn("-noavc", cmd)
        self.assertIn("-opendml", cmd)
        self.assertIn("-timestamp", cmd)
        self.assertEqual(cmd[cmd.index("-guid") + 1], "abc")

    def test_bad_format(self):
        with self.assertRaises(ValueError):
            build_command(RecordConfig(format="mp4"), Path("/x/"))


class StatusTests(unittest.TestCase):
    def test_sequence(self):
        st = RecorderState()
        self.assertEqual(apply_line(st, "Capture Started"), "started")
        ev = apply_line(st, '"clip-a.dv":    12.50 MiB    90 frames timecode 00:00:03.15 date 2026.10.07 17:00:01')
        self.assertEqual(ev, "clip")
        self.assertEqual((st.file, st.size_mib, st.frames, st.timecode, st.date),
                         ("clip-a.dv", 12.5, 90, "00:00:03.15", "2026.10.07 17:00:01"))
        self.assertEqual(apply_line(st, '"clip-a.dv":    13.00 MiB    95 frames'), "progress")
        self.assertEqual(apply_line(st, "Capture Stopped"), "stopped")
        self.assertEqual(st.state, "paused")
        self.assertEqual(apply_line(st, "Error: no camera exists"), "error")


class RecorderTests(unittest.TestCase):
    def test_supervises_and_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = RecordConfig(out_dir=Path(d), dvgrab=FAKE, retry_delay=0.1, min_free_gb=0)
            events = []
            rec = Recorder(cfg, on_event=lambda ev, st: events.append(ev))

            def stop_after_restart():
                while events.count("started") < 2:
                    threading.Event().wait(0.02)
                rec.stop()

            t = threading.Thread(target=stop_after_restart, daemon=True)
            t.start()
            self.assertEqual(rec.run(), 0)
            t.join(5)
            self.assertGreaterEqual(events.count("started"), 2)
            self.assertIn("clip", events)
            self.assertIn("waiting", events)
            self.assertEqual(rec.state.state, "stopped")
            self.assertTrue(rec.state.clips[0].endswith("2026.10.07_17-00-01.dv"))

    def test_missing_dvgrab(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = RecordConfig(out_dir=Path(d), dvgrab="/no/such/dvgrab",
                               retry_delay=0.05, min_free_gb=0)
            rec = Recorder(cfg)
            threading.Timer(0.3, rec.stop).start()
            rec.run()
            self.assertEqual(rec.state.state, "stopped")


if __name__ == "__main__":
    unittest.main()
