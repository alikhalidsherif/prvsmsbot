import unittest

from prvsmsbot.categories import MessageCategoryRules, classify_origin


class CategoryTests(unittest.TestCase):
    def test_classify_bank_service(self) -> None:
        rules = MessageCategoryRules(
            service_patterns=("telebirr", "127", "cbe"),
            personal_min_digits=10,
        )
        got = classify_origin("127", "CBE alert balance changed", rules)
        self.assertEqual(got["kind"], "service")
        self.assertEqual(got["origin"], "bank")

    def test_classify_personal(self) -> None:
        rules = MessageCategoryRules(
            service_patterns=("telebirr",),
            personal_min_digits=10,
        )
        got = classify_origin("+251911223344", "hey", rules)
        self.assertEqual(got["kind"], "personal")


if __name__ == "__main__":
    unittest.main()
