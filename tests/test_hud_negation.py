import unittest

from src.scene_design.system_contract import hud_spatial_emphasis


class HudNegationTests(unittest.TestCase):
    def test_prohibitions_and_actual_motion(self):
        cases = [
            ('Nhấp sáng bằng màu hoặc độ sáng tại neo (0;5,5), không dịch chuyển, xoay hoặc đổi kích thước.', False),
            ('không dịch chuyển, xoay hoặc đổi kích thước; sau đó xoay', True),
            ('không dịch chuyển nhưng xoay', True),
            ('không rung và xoay', False),
            ('không rung nhưng xoay', True),
            ('no geometric shake; move the counter', True),
            ('do not scale but shake', True),
            ('without any spatial shake or geometric scale', False),
            ('tịnh tiến bộ đếm', True),
            ('đổi kích thước', True),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(hud_spatial_emphasis(text), expected)


if __name__ == '__main__':
    unittest.main()
