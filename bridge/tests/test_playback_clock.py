import unittest
from bridge.playback_clock import PlaybackClock


class PlaybackClockTests(unittest.TestCase):
    def test_irregular_ticks_do_not_change_selected_rate(self):
        for speed in (1,2,5,10):
            clock=PlaybackClock(100000,0)
            clock.control(0,running=True,speed=speed)
            for now in (0.025,0.051,0.200,0.201,1.1,2.0):
                self.assertAlmostEqual(clock.value(now),now*1000*speed)

    def test_speed_change_accounts_old_rate_up_to_control_time(self):
        clock=PlaybackClock(100000,0);clock.control(0,running=True)
        clock.control(0.111,speed=5)
        self.assertAlmostEqual(clock.value(0.200),111+89*5)
        clock.control(0.2,running=False)
        self.assertEqual(clock.value(10),clock.value(0.2))
        clock.control(10,running=True)
        self.assertAlmostEqual(clock.value(10.1),111+89*5+500)

    def test_restart_and_end_are_bounded(self):
        clock=PlaybackClock(200,0);clock.control(0,running=True,speed=10)
        self.assertEqual(clock.value(1),200)
        restarted=PlaybackClock(200,1)
        self.assertEqual(restarted.value(1),0)

    def test_outgoing_clock_ignores_topic_event_timestamp_and_stamps_after_work(self):
        from unittest.mock import patch
        from bridge.server import Bridge
        bridge=Bridge()
        bridge.clip={'originMs':1000,'durationMs':10000}
        bridge.timeline=PlaybackClock(10000,0)
        bridge.timeline.control(0,running=True,speed=2)
        bridge.state.reset('TEST');bridge.state.playback='playing';bridge.state.speed=2
        bridge.state.clock_ms=-999  # An old archived event temporarily in state.
        with patch('bridge.server.time.monotonic',return_value=0.125):
            first=bridge.transport_message('clock')
        bridge.state.clock_ms=123
        with patch('bridge.server.time.monotonic',return_value=0.900):
            second=bridge.transport_message('clock')
        self.assertEqual(first['clockMs'],1250)
        self.assertEqual(second['clockMs'],2800)
        self.assertEqual((second['clockMs']-first['clockMs'])/(second['transportMs']-first['transportMs']),2)
