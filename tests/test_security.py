import unittest

from prvsmsbot.security import check_user_access


class SecurityTests(unittest.TestCase):
    def test_allowed_user(self) -> None:
        d = check_user_access((8338441637, 943629543), 943629543)
        self.assertTrue(d.allowed)

    def test_denied_user(self) -> None:
        d = check_user_access((8338441637, 943629543), 111111)
        self.assertFalse(d.allowed)


if __name__ == "__main__":
    unittest.main()
