from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0003_branch_alter_group_options_alter_script_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScriptImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="scripts/")),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("script", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="images", to="scripts.script")),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
    ]
