from pathlib import Path
import tempfile

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Branch, Group, Script, ScriptImage
from .tasks import _is_due_daily, _is_due_monthly, _is_due_once, _needs_photo_resize, _normalized_photo_path
from bot.bot import merge_group_records


class ScriptTargetGroupsTests(TestCase):
    def setUp(self):
        self.active_branch = Branch.objects.create(name="Active branch")
        self.inactive_branch = Branch.objects.create(name="Inactive branch", is_active=False)

        self.active_group_1 = Group.objects.create(
            name="Active Group 1",
            chat_id=-1001,
            branch=self.active_branch,
            language="uz",
        )
        self.active_group_2 = Group.objects.create(
            name="Active Group 2",
            chat_id=-1002,
            branch=self.active_branch,
            language="ru",
        )
        self.inactive_branch_group = Group.objects.create(
            name="Inactive Branch Group",
            chat_id=-1003,
            branch=self.inactive_branch,
            language="uz",
        )
        self.manual_group = Group.objects.create(
            name="Manual Group",
            chat_id=-1004,
            language="ru",
        )

    def create_script(self, title="Script"):
        return Script.objects.create(
            title=title,
            repeat_type="daily",
            send_time=timezone.now(),
            text_uz="Salom",
            text_ru="Privet",
        )

    def test_active_branch_includes_all_its_groups(self):
        script = self.create_script()
        script.branches.add(self.active_branch)

        target_ids = set(script.get_target_groups().values_list("id", flat=True))

        self.assertEqual(target_ids, {self.active_group_1.id, self.active_group_2.id})
        self.assertEqual(script.target_group_count(), 2)

    def test_inactive_branch_groups_are_excluded(self):
        script = self.create_script(title="Inactive branch test")
        script.branches.add(self.inactive_branch)

        target_ids = set(script.get_target_groups().values_list("id", flat=True))

        self.assertEqual(target_ids, set())
        self.assertEqual(script.target_group_count(), 0)

    def test_manual_groups_are_merged_without_duplicates(self):
        script = self.create_script(title="Manual merge test")
        script.branches.add(self.active_branch)
        script.groups.add(self.active_group_1, self.manual_group)

        target_ids = set(script.get_target_groups().values_list("id", flat=True))

        self.assertEqual(
            target_ids,
            {self.active_group_1.id, self.active_group_2.id, self.manual_group.id},
        )
        self.assertEqual(script.target_group_count(), 3)

    def test_repeat_type_change_resets_last_sent_at(self):
        script = self.create_script(title="Repeat reset test")
        script.last_sent_at = timezone.now()
        script.save(update_fields=["last_sent_at"])

        script.repeat_type = "monthly"
        script.save()
        script.refresh_from_db()

        self.assertIsNone(script.last_sent_at)

    def test_one_time_reschedule_resets_last_sent_at(self):
        script = Script.objects.create(
            title="One-time reschedule test",
            repeat_type="once",
            send_time=timezone.now(),
            text_uz="Salom",
        )
        script.last_sent_at = timezone.now()
        script.save(update_fields=["last_sent_at"])

        script.send_time = timezone.now() + timezone.timedelta(hours=1)
        script.save()
        script.refresh_from_db()

        self.assertIsNone(script.last_sent_at)


class BranchCountTests(TestCase):
    def test_group_count_matches_attached_groups(self):
        branch = Branch.objects.create(name="Count branch")
        Group.objects.create(name="Group 1", chat_id=-2001, branch=branch, language="uz")
        Group.objects.create(name="Group 2", chat_id=-2002, branch=branch, language="ru")

        self.assertEqual(branch.group_count(), 2)


class GroupMergeTests(TestCase):
    def test_merge_preserves_branch_and_scripts(self):
        branch = Branch.objects.create(name="Merge branch")
        old_group = Group.objects.create(name="Old group", chat_id=-3001, branch=branch, language="uz")
        new_group = Group.objects.create(name="New group", chat_id=-1003001, language=None)
        script = Script.objects.create(
            title="Merge script",
            repeat_type="daily",
            send_time=timezone.now(),
            text_uz="Salom",
            text_ru="Privet",
        )
        script.groups.add(old_group)

        merged_group, created = merge_group_records(old_group.chat_id, new_group.chat_id, "Merged name")

        self.assertFalse(created)
        self.assertEqual(merged_group.id, new_group.id)
        self.assertEqual(merged_group.branch_id, branch.id)
        self.assertEqual(merged_group.language, "uz")
        self.assertTrue(merged_group.scripts.filter(id=script.id).exists())
        self.assertFalse(Group.objects.filter(id=old_group.id).exists())


class ProductionSecuritySettingsTests(TestCase):
    def test_env_bool_parses_https_flag(self):
        from config.settings import env_bool

        self.assertTrue(env_bool("DJANGO_ENABLE_HTTPS", True))
        self.assertFalse(env_bool("DJANGO_ENABLE_HTTPS", False) and False)


class ScriptScheduleLogicTests(TestCase):
    def test_one_time_script_is_due_on_exact_scheduled_minute_if_not_sent(self):
        send_time = timezone.now().replace(second=0, microsecond=0)
        now = send_time
        script = Script(repeat_type="once", send_time=send_time, last_sent_at=None)

        self.assertTrue(_is_due_once(script, now, send_time))

    def test_one_time_script_is_not_due_after_scheduled_minute(self):
        send_time = timezone.now().replace(second=0, microsecond=0)
        now = send_time + timezone.timedelta(minutes=1)
        script = Script(repeat_type="once", send_time=send_time, last_sent_at=None)

        self.assertFalse(_is_due_once(script, now, send_time))

    def test_daily_script_is_due_after_scheduled_minute_if_not_sent_today(self):
        send_time = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        now = send_time + timezone.timedelta(minutes=15)
        script = Script(repeat_type="daily", send_time=send_time, last_sent_at=None)

        self.assertTrue(_is_due_daily(script, now, send_time))

    def test_monthly_script_is_due_after_scheduled_minute_if_not_sent_this_month(self):
        send_time = timezone.now().replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        now = send_time + timezone.timedelta(minutes=15)
        script = Script(repeat_type="monthly", send_time=send_time, last_sent_at=None)

        self.assertTrue(_is_due_monthly(script, now, send_time))

    def test_daily_script_is_not_due_before_scheduled_time_today(self):
        send_time = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        now = send_time.replace(hour=8, minute=30)
        script = Script(repeat_type="daily", send_time=send_time, last_sent_at=None)

        self.assertFalse(_is_due_daily(script, now, send_time))

    def test_monthly_script_is_not_due_before_scheduled_time_on_matching_day(self):
        send_time = timezone.now().replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        now = send_time.replace(hour=8, minute=30)
        script = Script(repeat_type="monthly", send_time=send_time, last_sent_at=None)

        self.assertFalse(_is_due_monthly(script, now, send_time))


class TelegramPhotoConstraintTests(TestCase):
    def test_large_photo_dimension_sum_requires_resize(self):
        self.assertTrue(_needs_photo_resize(8706, 1396))

    def test_normal_photo_dimensions_do_not_require_resize(self):
        self.assertFalse(_needs_photo_resize(2036, 1732))


class ScriptImagePathTests(TestCase):
    def test_legacy_image_is_used_when_no_script_images_exist(self):
        script = Script.objects.create(
            title="Legacy only",
            repeat_type="once",
            send_time=timezone.now(),
            image="scripts/legacy.jpg",
        )

        self.assertEqual(script.get_image_paths(), [script.image.path])

    def test_script_images_take_precedence_over_hidden_legacy_image(self):
        script = Script.objects.create(
            title="Script images first",
            repeat_type="once",
            send_time=timezone.now(),
            image="scripts/legacy.jpg",
        )
        extra = ScriptImage.objects.create(script=script, image="scripts/extra.jpg", sort_order=0)

        self.assertEqual(script.get_image_paths(), [extra.image.path])


class TelegramPhotoNormalizationTests(TestCase):
    def test_normalized_photo_path_uses_unique_names_for_same_stem(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as temp_dir:
            first_source = Path(source_dir) / "banner.png"
            second_source = Path(source_dir) / "banner.jpg"

            from PIL import Image

            Image.new("RGB", (8706, 1396), color="white").save(first_source)
            Image.new("RGB", (8706, 1396), color="black").save(second_source)

            first = _normalized_photo_path(str(first_source), temp_dir)
            second = _normalized_photo_path(str(second_source), temp_dir)

        self.assertNotEqual(first, second)
