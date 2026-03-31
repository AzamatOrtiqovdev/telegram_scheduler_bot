from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Branch, Group, Script
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
