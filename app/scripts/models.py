from django.db import models


class Branch(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Branch"
        verbose_name_plural = "Branches"

    def __str__(self):
        return self.name

    def group_count(self):
        if hasattr(self, "group_count_value"):
            return self.group_count_value

        prefetched_groups = getattr(self, "_prefetched_objects_cache", {}).get("groups")
        if prefetched_groups is not None:
            return len(prefetched_groups)

        return self.groups.count()


class Group(models.Model):
    LANGUAGE_CHOICES = [
        ("uz", "Uzbek"),
        ("ru", "Russian"),
    ]

    name = models.CharField(max_length=255)
    chat_id = models.BigIntegerField(unique=True)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="groups",
        blank=True,
        null=True,
    )
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        language = self.language or "no-lang"
        branch_name = self.branch.name if self.branch else "no-branch"
        return f"{self.name} ({language}) | {branch_name} | {self.chat_id}"


class Script(models.Model):
    REPEAT_CHOICES = [
        ("once", "Bir marta"),
        ("daily", "Har kuni"),
        ("monthly", "Har oy"),
    ]

    title = models.CharField(max_length=255)
    text_uz = models.TextField(blank=True, null=True)
    text_ru = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to="scripts/", blank=True, null=True)
    repeat_type = models.CharField(max_length=20, choices=REPEAT_CHOICES, default="once")
    send_time = models.DateTimeField()
    branches = models.ManyToManyField(Branch, blank=True, related_name="scripts")
    groups = models.ManyToManyField(Group, blank=True, related_name="scripts")
    is_active = models.BooleanField(default=True)
    last_sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["title"]

    def save(self, *args, **kwargs):
        if self.pk and self._repeat_type_changed():
            self.last_sent_at = None
        super().save(*args, **kwargs)

    def _repeat_type_changed(self) -> bool:
        old_script = type(self).objects.filter(pk=self.pk).only("repeat_type").first()
        return bool(old_script and old_script.repeat_type != self.repeat_type)

    def _prefetched_relation_cache(self, relation_name: str):
        return getattr(self, "_prefetched_objects_cache", {}).get(relation_name)

    def _prefetched_branch_group_ids(self) -> set[int]:
        prefetched_branches = self._prefetched_relation_cache("branches")
        if prefetched_branches is None:
            return set()

        return {
            group.id
            for branch in prefetched_branches
            if branch.is_active
            for group in getattr(branch, "_prefetched_objects_cache", {}).get("groups", [])
            if group.id is not None
        }

    def _selected_group_ids(self) -> set[int]:
        prefetched_groups = self._prefetched_relation_cache("groups")
        if prefetched_groups is not None:
            return {group.id for group in prefetched_groups if group.id is not None}

        return set(self.groups.values_list("id", flat=True))

    def _branch_group_ids(self) -> set[int]:
        return set(
            self.branches.filter(is_active=True)
            .values_list("groups__id", flat=True)
            .exclude(groups__id__isnull=True)
        )

    def _get_target_group_ids(self):
        prefetched_branches = self._prefetched_relation_cache("branches")
        prefetched_groups = self._prefetched_relation_cache("groups")

        if prefetched_branches is not None and prefetched_groups is not None:
            return self._prefetched_branch_group_ids().union(self._selected_group_ids())

        return self._branch_group_ids().union(self._selected_group_ids())

    def get_target_groups(self):
        return Group.objects.filter(id__in=self._get_target_group_ids()).select_related("branch")

    def target_group_count(self):
        return len(self._get_target_group_ids())

    def __str__(self):
        return self.title
