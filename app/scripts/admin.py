from django.contrib import admin
from django.db.models import Count, Prefetch, Q

from .models import Branch, Group, Script

ADMIN_SITE_TITLE = "Times School Notification bot"
CONTENT_TEXT_QUERY = (Q(text_uz__isnull=False) & ~Q(text_uz="")) | (Q(text_ru__isnull=False) & ~Q(text_ru=""))
CONTENT_IMAGE_QUERY = Q(image__isnull=False) & ~Q(image="")
SCRIPT_BRANCH_PREFETCH = Prefetch("branches", queryset=Branch.objects.prefetch_related("groups"))

admin.site.site_header = ADMIN_SITE_TITLE
admin.site.site_title = ADMIN_SITE_TITLE
admin.site.index_title = ADMIN_SITE_TITLE

HIDDEN_ADMIN_APP_LABELS = {"auth"}


def _filtered_app_list(request, app_label=None):
    app_list = original_get_app_list(request, app_label)
    return [app for app in app_list if app["app_label"] not in HIDDEN_ADMIN_APP_LABELS]


class MappedValueFilter(admin.SimpleListFilter):
    value_map = {}

    def queryset(self, request, queryset):
        value = self.value()
        if value not in self.value_map:
            return queryset
        return self.value_map[value](queryset)


class BranchUsageFilter(MappedValueFilter):
    title = "usage"
    parameter_name = "usage"
    value_map = {
        "with_groups": lambda qs: qs.filter(group_count_value__gt=0),
        "without_groups": lambda qs: qs.filter(group_count_value=0),
        "with_scripts": lambda qs: qs.filter(script_count_value__gt=0),
        "without_scripts": lambda qs: qs.filter(script_count_value=0),
    }

    def lookups(self, request, model_admin):
        return (
            ("with_groups", "Has groups"),
            ("without_groups", "No groups"),
            ("with_scripts", "Used in scripts"),
            ("without_scripts", "Not used in scripts"),
        )


class GroupBranchAssignmentFilter(MappedValueFilter):
    title = "branch assignment"
    parameter_name = "branch_assignment"
    value_map = {
        "assigned": lambda qs: qs.filter(branch__isnull=False),
        "unassigned": lambda qs: qs.filter(branch__isnull=True),
    }

    def lookups(self, request, model_admin):
        return (
            ("assigned", "Assigned to branch"),
            ("unassigned", "Without branch"),
        )


class ScriptRecipientModeFilter(MappedValueFilter):
    title = "recipient mode"
    parameter_name = "recipient_mode"
    value_map = {
        "branches_only": lambda qs: qs.filter(branches_count__gt=0, groups_count=0),
        "groups_only": lambda qs: qs.filter(branches_count=0, groups_count__gt=0),
        "mixed": lambda qs: qs.filter(branches_count__gt=0, groups_count__gt=0),
        "empty": lambda qs: qs.filter(branches_count=0, groups_count=0),
    }

    def lookups(self, request, model_admin):
        return (
            ("branches_only", "Branches only"),
            ("groups_only", "Groups only"),
            ("mixed", "Branches + groups"),
            ("empty", "No recipients"),
        )


class ScriptContentFilter(MappedValueFilter):
    title = "content"
    parameter_name = "content"
    value_map = {
        "image_only": lambda qs: qs.filter(CONTENT_IMAGE_QUERY).exclude(CONTENT_TEXT_QUERY),
        "text_only": lambda qs: qs.filter(CONTENT_TEXT_QUERY).exclude(CONTENT_IMAGE_QUERY),
        "image_and_text": lambda qs: qs.filter(CONTENT_TEXT_QUERY, CONTENT_IMAGE_QUERY),
        "empty": lambda qs: qs.exclude(CONTENT_TEXT_QUERY).exclude(CONTENT_IMAGE_QUERY),
    }

    def lookups(self, request, model_admin):
        return (
            ("image_only", "Image only"),
            ("text_only", "Text only"),
            ("image_and_text", "Image + text"),
            ("empty", "No content"),
        )


class ScriptSendStatusFilter(MappedValueFilter):
    title = "send status"
    parameter_name = "send_status"
    value_map = {
        "sent": lambda qs: qs.filter(last_sent_at__isnull=False),
        "never_sent": lambda qs: qs.filter(last_sent_at__isnull=True),
    }

    def lookups(self, request, model_admin):
        return (
            ("sent", "Sent before"),
            ("never_sent", "Never sent"),
        )


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "group_count", "is_active")
    search_fields = ("name", "groups__name", "groups__chat_id")
    list_filter = ("is_active", BranchUsageFilter)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            group_count_value=Count("groups", distinct=True),
            script_count_value=Count("scripts", distinct=True),
        )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "language", "chat_id", "is_active")
    list_filter = (GroupBranchAssignmentFilter, "branch", "language", "is_active", "branch__is_active")
    search_fields = ("name", "chat_id", "branch__name")
    autocomplete_fields = ("branch",)
    list_select_related = ("branch",)


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "repeat_type",
        "send_time",
        "last_sent_at",
        "target_group_count",
        "is_active",
    )
    list_filter = (
        "repeat_type",
        "is_active",
        ScriptSendStatusFilter,
        ScriptRecipientModeFilter,
        ScriptContentFilter,
        "branches",
    )
    search_fields = ("title", "text_uz", "text_ru", "branches__name", "groups__name")
    filter_horizontal = ("branches", "groups")
    date_hierarchy = "send_time"
    fieldsets = (
        (None, {"fields": ("title", "repeat_type", "send_time", "is_active")}),
        ("Content", {"fields": ("text_uz", "text_ru", "image")}),
        (
            "Recipients",
            {
                "fields": ("branches", "groups"),
                "description": (
                    "Branch tanlansa, osha branchdagi barcha guruhlarga yuboriladi. "
                    "Groups orqali esa aniq guruhlarni qoshimcha tanlash mumkin."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                branches_count=Count("branches", distinct=True),
                groups_count=Count("groups", distinct=True),
            )
            .prefetch_related(SCRIPT_BRANCH_PREFETCH, "groups")
        )

original_get_app_list = admin.site.get_app_list
admin.site.get_app_list = _filtered_app_list


