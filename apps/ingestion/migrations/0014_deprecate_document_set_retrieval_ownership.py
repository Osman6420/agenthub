"""Relax document-set retrieval ownership without touching a single row.

Query-time retrieval behavior now comes from the executing Retrieve node's binding, so a
document set no longer has to name a retrieval profile. This migration only drops the NOT
NULL constraint; every existing reference is preserved as historical provenance.

Rollout: a catalog-only ``ALTER COLUMN … DROP NOT NULL``. No data is rewritten, no index is
rebuilt and no table is scanned, so the lock is brief and the change is safe while the
application is serving.

Rollback: the reverse operation restores NOT NULL and therefore only succeeds while no row
has a null ``retrieval_profile_id``. Once a preparation profile has been saved without one,
the forward fix is to keep the column nullable rather than to reverse this migration.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("artifacts", "0006_artifactversion_descriptions"),
        ("ingestion", "0013_atomic_served_index_constraint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documentsetpreparationprofile",
            name="retrieval_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_preparation_retrieval_profiles",
                to="artifacts.artifactversion",
            ),
        ),
    ]
