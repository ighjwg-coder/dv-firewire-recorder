import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dvrec.panel import PAGES, Panel, PanelConfig, Snapshot, fmt_elapsed, fmt_remaining, render
from dvrec.recorder import Recorder, RecordConfig, build_command

FAKE = str(Path(__file__).with_name("fake_dvgrab.py"))


def snap(**kw):
    base = dict(camera=True, state="recording", armed=True, mode="manual", elapsed=3725,
                clips=2, total_gb=100.0, used_gb=74.0, free_gb=26.0,
                ip="10.0.0.5", hostname="firepi")
    base.update(kw)
    return Snapshot(**base)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class RenderTests(unittest.TestCase):
    def test_formatters(self):
        self.assertEqual(fmt_elapsed(3725), "01:02:05")
        self.assertEqual(fmt_remaining(26.0), "2h00m")
        self.assertEqual(fmt_remaining(6.5), "30m")

    def test_record_page(self):
        lines = render("RECORD", snap())
        self.assertTrue(lines[0].startswith("RECORD"))
        self.assertIn("26%", lines[0])
        self.assertEqual(lines[2], "01:02:05")
        self.assertIn("REC", lines[3])
        self.assertEqual(render("RECORD", snap(camera=False))[2], "NO CAM")
        self.assertEqual(render("RECORD", snap(state="standby"))[2], "STBY")

    def test_other_pages_fit_display(self):
        for page in PAGES:
            for ln in render(page, snap(), power_choice=1):
                self.assertLessEqual(len(ln), 21, (page, ln))
        self.assertIn("> Shutdown", render("POWER", snap(), 1))
        self.assertIn("10.0.0.5", render("NETWORK", snap()))


class ManualModeTests(unittest.TestCase):
    def setUp(self):
        os.environ["FAKE_DVGRAB_HOLD"] = "1"

    def tearDown(self):
        os.environ.pop("FAKE_DVGRAB_HOLD", None)

    def test_command(self):
        cmd = build_command(RecordConfig(mode="manual"), Path("/x/c-"))
        self.assertIn("-noavc", cmd)
        self.assertNotIn("-r", cmd)

    def test_toggle_starts_and_stops_dvgrab(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = RecordConfig(out_dir=Path(d), mode="manual", dvgrab=FAKE,
                               retry_delay=0.1, min_free_gb=0)
            rec = Recorder(cfg)
            t = threading.Thread(target=rec.run, daemon=True)
            t.start()
            self.assertTrue(wait_for(lambda: rec.state.state == "standby"))

            self.assertTrue(rec.toggle_record())
            self.assertTrue(wait_for(lambda: rec.state.rec_since is not None))
            self.assertEqual(rec.state.state, "recording")

            rec.toggle_record()
            self.assertTrue(wait_for(lambda: rec.state.state == "standby"))
            self.assertIsNone(rec.state.rec_since)

            rec.stop()
            t.join(5)
            self.assertFalse(t.is_alive())

    def test_toggle_ignored_in_tapeless(self):
        self.assertFalse(Recorder(RecordConfig()).toggle_record())


class PanelTests(unittest.TestCase):
    def test_power_menu_shutdown(self):
        rec = Recorder(RecordConfig())
        calls = []
        panel = Panel(rec, PanelConfig(display="none"), power_cmd=calls.append)
        for _ in range(3):
            panel.on_page()
        self.assertEqual(PAGES[panel.page], "POWER")
        panel.on_select_hold()          # "Cancel" selected → back to RECORD, nothing runs
        self.assertEqual(PAGES[panel.page], "RECORD")
        self.assertEqual(calls, [])

        for _ in range(3):
            panel.on_page()
        panel.on_select()               # → Shutdown
        panel.on_select_hold()
        self.assertEqual(calls, ["poweroff"])
        self.assertTrue(rec._stop.is_set())


if __name__ == "__main__":
    unittest.main()
