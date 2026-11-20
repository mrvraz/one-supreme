from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0004_feature_parity"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="post",
            options={
                "ordering": ["-created_at"],
                "permissions": [("publish_news", "Can publish news"), ("view_insights", "Can view usage figures")],
            },
        ),
    ]
