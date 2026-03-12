from django.db import models


class Group(models.Model):
    LANGUAGE_CHOICES = [
        ("uz", "Uzbek"),
        ("ru", "Russian"),
    ]

    name = models.CharField(max_length=255)
    chat_id = models.BigIntegerField(unique=True)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        lang = self.language if self.language else "no-lang"
        return f"{self.name} ({lang}) | {self.chat_id}"


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
    groups = models.ManyToManyField(Group)

    is_active = models.BooleanField(default=True)
    last_sent_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.pk:
            old = Script.objects.filter(pk=self.pk).first()
            if old and old.repeat_type != self.repeat_type:
                self.last_sent_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
