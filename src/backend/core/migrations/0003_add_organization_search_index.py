# Generated manually for improved search performance with GIN indexes

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_operatorserviceconfig_service_operators_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            # Create GIN indexes for better ILIKE performance with unaccent
            sql="""
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE EXTENSION IF NOT EXISTS unaccent;

            -- Create immutable unaccent function since indexes require immutable functions
            CREATE OR REPLACE FUNCTION unaccent_immutable(text) 
            RETURNS text AS $$ 
                SELECT public.unaccent($1);
            $$ LANGUAGE sql IMMUTABLE;
            
            CREATE INDEX IF NOT EXISTS idx_organization_name_gin_trgm 
            ON deploycenter_organization 
            USING gin (unaccent_immutable(name) gin_trgm_ops);
            
            CREATE INDEX IF NOT EXISTS idx_organization_departement_gin_trgm 
            ON deploycenter_organization 
            USING gin (unaccent_immutable(departement_code_insee) gin_trgm_ops);
            
            CREATE INDEX IF NOT EXISTS idx_organization_epci_gin_trgm 
            ON deploycenter_organization 
            USING gin (unaccent_immutable(epci_libelle) gin_trgm_ops);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_organization_name_gin_trgm;
            DROP INDEX IF EXISTS idx_organization_departement_gin_trgm;
            DROP INDEX IF EXISTS idx_organization_epci_gin_trgm;
            DROP FUNCTION IF EXISTS unaccent_immutable(text);
            """,
        ),
    ]


