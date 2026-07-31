from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
WEB = ROOT / "event-tool" / "web"


def test_playwright_openerless_calculator_return_page_broadcast_e2e() -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    calculator = r"""
<!doctype html><meta charset="utf-8"><script>
const encoded=new URLSearchParams(location.hash.slice(1)).get("aipol_context");
const padded=encoded.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-encoded.length%4)%4);
const launch=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(padded),c=>c.charCodeAt(0))));
if (opener !== null) throw new Error("reverse tabnabbing boundary failed");
const protectedHeader=btoa(JSON.stringify({alg:"EdDSA",kid:"calculator-key-1",typ:"JWT"})).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
const value={contract_version:launch.contract_version,channel_id:launch.channel_id,
  experiment_id:launch.context.experiment_id,
  receipt:{protected:protectedHeader,payload:"payload",signature:"signature"}};
const raw=btoa(JSON.stringify(value)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
location.replace(launch.return_url+"#aipol_return="+raw);
</script>
"""

    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_context = browser.new_context()

        def aipol_route(route):
            path = route.request.url.split("https://aipol.example", 1)[-1]
            files = {
                "/aipol-calculator-return.html": WEB / "aipol-calculator-return.html",
                "/aipol-receipt.js": WEB / "aipol-receipt.js",
                "/aipol-calculator-return.js": WEB / "aipol-calculator-return.js",
                "/aipol.css": WEB / "aipol.css",
            }
            if path in files:
                content_type = "text/javascript" if path.endswith(".js") else "text/html"
                route.fulfill(status=200, content_type=content_type, body=files[path].read_text("utf-8"))
            else:
                route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>AIPOL parent</title>")

        browser_context.route("https://calculator.example/**", lambda route: route.fulfill(status=200, content_type="text/html", body=calculator))
        browser_context.route("https://aipol.example/**", aipol_route)
        page = browser_context.new_page()
        page.goto("https://aipol.example/parent", wait_until="networkidle")
        page.add_script_tag(path=str(WEB / "aipol-receipt.js"))
        result = page.evaluate(
            """async () => {
              const receiptContext={experiment_id:'xp',experiment_version:'v1',session_id:'s1',
                participant_pseudonym:'participant-1',artifact_id:'calc',
                artifact_hash:'a'.repeat(64),contract_hash:'b'.repeat(64)};
              const integration={contract_version:AipolReceipt.CONTRACT_VERSION,
                allowed_origin:'https://calculator.example',launch_url:'https://calculator.example/run',
                context_fragment_key:'aipol_context',max_context_bytes:2048};
              const channelId=crypto.randomUUID();
              const returnUrl='https://aipol.example/aipol-calculator-return.html';
              const launch=AipolReceipt.buildLaunchUrl(integration,receiptContext,returnUrl,channelId,location.origin);
              let received=null;
              const dispose=AipolReceipt.createReturnChannel({channelId,context:receiptContext,
                BroadcastChannelClass:BroadcastChannel,onReceipt:value=>{received=value;}});
              window.open(launch,'_blank','noopener,noreferrer,popup,width=900,height=760');
              const deadline=Date.now()+5000;
              while(!received && Date.now()<deadline) await new Promise(resolve=>setTimeout(resolve,25));
              dispose(); return {launch,received};
            }"""
        )
        browser.close()

    assert result["launch"].startswith("https://calculator.example/run#aipol_context=")
    assert result["received"]["payload"] == "payload"
    protected = json.loads(base64.urlsafe_b64decode(result["received"]["protected"] + "=="))
    assert protected == {"alg": "EdDSA", "kid": "calculator-key-1", "typ": "JWT"}

