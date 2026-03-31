from django.db import migrations


def copy_legacy_script_images(apps, schema_editor):
    Script = apps.get_model("scripts", "Script")
    ScriptImage = apps.get_model("scripts", "ScriptImage")

    for script in Script.objects.exclude(image="").exclude(image__isnull=True):
        if ScriptImage.objects.filter(script_id=script.id).exists():
            continue

        ScriptImage.objects.create(
            script_id=script.id,
            image=script.image,
            sort_order=0,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0004_scriptimage"),
    ]

    operations = [
        migrations.RunPython(copy_legacy_script_images, noop_reverse),
    ]
