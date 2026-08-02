# Privacy Notice

Timeline CTI Explorer is designed for a single authenticated operator.

## Selenium backend (default)

With `COLLECTOR_BACKEND=selenium`, the collector processes posts visible in the operator's own authenticated X home timeline during each scroll session. Browser cookies are stored encrypted in the local SQLite state database and are never written to the repository.

## X API backend (optional)

With `COLLECTOR_BACKEND=api`, the collector processes posts returned by that operator's official X home-timeline authorization and stores OAuth tokens encrypted at rest.

## Stored data

In both modes the system stores post text, public author metadata, public engagement metrics, extracted indicators and derived CTI scores. It does not download media, collect direct messages, train models on X content, or intentionally associate X identities with off-platform identities.

Protected-author posts are rejected. Real content is not included in repository fixtures and bulk full-text export is not implemented. Operators remain responsible for their legal basis, disclosure, retention and deletion obligations.

To remove live X data, stop collector/worker, revoke OAuth access or delete imported browser cookies from the state database, and delete the relevant ClickHouse rows or volume in accordance with applicable policy and law. Selenium-collected rows are not automatically reconciled through X Batch Compliance.

## Türkçe

Uygulama tek yetkili operatör içindir. Selenium modunda yalnız operatörün kendi ana sayfa akışı işlenir; cookie’ler şifreli state veritabanında tutulur. API modunda resmî OAuth yetkisi kullanılır. Medya veya DM indirilmez, X içeriğiyle model eğitilmez. Hukuki dayanak, aydınlatma, saklama ve silme sorumluluğu operatöre aittir.
