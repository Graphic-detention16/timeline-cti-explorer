# X Content Compliance

## Selenium backend (default)

`COLLECTOR_BACKEND=selenium` automates a logged-in browser session against the operator's own X home timeline (Following and For You). This mode:

- does **not** use the official X API or OAuth user context;
- may conflict with [X's Terms of Service](https://x.com/en/tos) and [Developer Policy](https://docs.x.com/developer-terms/policy);
- does **not** run Batch Compliance deletion jobs against collected rows;
- stores only posts visible in the authenticated home timeline during each scroll window;
- enforces a local daily read budget and durable spool backpressure;
- does not provide anonymous access or bulk full-text export;
- does not train or fine-tune a model on X content;
- distributes only deterministic synthetic fixtures in the repository.

Operators remain solely responsible for lawful use, account security, cookie rotation and data retention.

## X API backend (optional)

When `COLLECTOR_BACKEND=api`, live mode is permitted only after the exact CTI use case has been disclosed and approved in the X Developer Console.

The API implementation:

- uses the official reverse-chronological home timeline and OAuth user context;
- does not scrape pages, automate a browser, rotate accounts or bypass rate limits;
- enforces a local daily read budget;
- runs Batch Compliance against stored X post IDs;
- applies deletion/protection/suspension events through ClickHouse lightweight deletes;
- does not provide anonymous access or bulk full-text export;
- does not train or fine-tune a model on X content;
- distributes only deterministic synthetic fixtures.

Policy and API behavior can change. Review the current [X Developer Policy](https://docs.x.com/developer-terms/policy), [timeline documentation](https://docs.x.com/x-api/posts/timelines/introduction), and [Batch Compliance documentation](https://docs.x.com/x-api/compliance/batch-compliance/introduction) before every production release.

## Türkçe

**Selenium (varsayılan):** Şifreli cookie oturumuyla kendi ana sayfa akışınız taranır; resmî API kullanılmaz, Batch Compliance uygulanmaz ve X politikalarıyla çakışma riski operatöre aittir.

**X API (opsiyonel):** CTI kullanım amacı onaylandıktan sonra resmî API, OAuth, günlük bütçe ve Batch Compliance devreye girer. Her production sürümünde güncel resmî metinler yeniden incelenmelidir.
