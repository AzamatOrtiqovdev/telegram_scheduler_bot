from django.contrib import admin
from django.db.models import Count, Prefetch, Q

admin.site.site_header = 'Times School Notification bot'
admin.site.site_title = 'Times School Notification bot'
admin.site.index_title = 'Times School Notification bot'

from .models import Branch, Group, Script


class BranchUsageFilter(admin.SimpleListFilter):
    title = "usage"
    parameter_name = "usage"

    def lookups(self, request, model_admin):
        return (
            ("with_groups", "Has groups"),
            ("without_groups", "No groups"),
            ("with_scripts", "Used in scripts"),
            ("without_scripts", "Not used in scripts"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "with_groups":
            return queryset.filter(group_count_value__gt=0)
        if value == "without_groups":
            return queryset.filter(group_count_value=0)
        if value == "with_scripts":
            return queryset.filter(script_count_value__gt=0)
        if value == "without_scripts":
            return queryset.filter(script_count_value=0)
        return queryset


class GroupBranchAssignmentFilter(admin.SimpleListFilter):
    title = "branch assignment"
    parameter_name = "branch_assignment"

    def lookups(self, request, model_admin):
        return (
            ("assigned", "Assigned to branch"),
            ("unassigned", "Without branch"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "assigned":
            return queryset.filter(branch__isnull=False)
        if value == "unassigned":
            return queryset.filter(branch__isnull=True)
        return queryset


class ScriptRecipientModeFilter(admin.SimpleListFilter):
    title = "recipient mode"
    parameter_name = "recipient_mode"

    def lookups(self, request, model_admin):
        return (
            ("branches_only", "Branches only"),
            ("groups_only", "Groups only"),
            ("mixed", "Branches + groups"),
            ("empty", "No recipients"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "branches_only":
            return queryset.filter(branches_count__gt=0, groups_count=0)
        if value == "groups_only":
            return queryset.filter(branches_count=0, groups_count__gt=0)
        if value == "mixed":
            return queryset.filter(branches_count__gt=0, groups_count__gt=0)
        if value == "empty":
            return queryset.filter(branches_count=0, groups_count=0)
        return queryset


class ScriptContentFilter(admin.SimpleListFilter):
    title = "content"
    parameter_name = "content"

    def lookups(self, request, model_admin):
        return (
            ("image_only", "Image only"),
            ("text_only", "Text only"),
            ("image_and_text", "Image + text"),
            ("empty", "No content"),
        )

    def queryset(self, request, queryset):
        has_text = Q(text_uz__isnull=False) & ~Q(text_uz="") | Q(text_ru__isnull=False) & ~Q(text_ru="")
        has_image = Q(image__isnull=False) & ~Q(image="")
        value = self.value()
        if value == "image_only":
            return queryset.filter(has_image).exclude(has_text)
        if value == "text_only":
            return queryset.filter(has_text).exclude(has_image)
        if value == "image_and_text":
            return queryset.filter(has_text, has_image)
        if value == "empty":
            return queryset.exclude(has_text).exclude(has_image)
        return queryset


class ScriptSendStatusFilter(admin.SimpleListFilter):
    title = "send status"
    parameter_name = "send_status"

    def lookups(self, request, model_admin):
        return (
            ("sent", "Sent before"),
            ("never_sent", "Never sent"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "sent":
            return queryset.filter(last_sent_at__isnull=False)
        if value == "never_sent":
            return queryset.filter(last_sent_at__isnull=True)
        return queryset


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "group_count", "is_active")
    search_fields = ("name", "groups__name", "groups__chat_id")
    list_filter = ("is_active", BranchUsageFilter)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(
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
        queryset = super().get_queryset(request)
        return queryset.annotate(
            branches_count=Count("branches", distinct=True),
            groups_count=Count("groups", distinct=True),
        ).prefetch_related(
            Prefetch("branches", queryset=Branch.objects.prefetch_related("groups")),
            "groups",
        )

