"""Build a minimal Apigee X/hybrid proxy bundle from the spec + form answers.

Output: work/proxy/apiproxy/... and work/<api-name>-proxy.zip, plus work/proxy.md (summary)
The bundle has: API key or OAuth check, spike arrest, one flow per operation, and a 404 for
anything not in the spec. Extend the policy templates to match your Apigee standards.
"""
import os
import re
import shutil
from xml.sax.saxutils import escape

import yaml

from common import WORK_DIR, load_form, pascal, set_output

METHODS = ("get", "put", "post", "delete", "patch", "head", "options")


def flow_condition(path: str, verb: str) -> str:
    pattern = re.sub(r"\{[^}]+\}", "*", path)
    return f'(proxy.pathsuffix MatchesPath "{pattern}") and (request.verb = "{verb.upper()}")'


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")


def main() -> None:
    form = load_form()
    with open(os.path.join(WORK_DIR, "spec.yaml"), encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    name = form["api_name"]
    base_path = form.get("base_path") or f"/{name}/v1"
    target = form["target_url"]
    rate = form.get("rate_limit") or "20ps"
    oauth = form.get("security", "").startswith("OAuth")
    auth_policy = "OAuth-VerifyToken" if oauth else "VerifyAPIKey"

    root = os.path.join(WORK_DIR, "proxy", "apiproxy")
    shutil.rmtree(os.path.dirname(root), ignore_errors=True)

    # One flow per operation, so analytics and future per-operation policies work out of the box
    flows = []
    for path, item in (spec.get("paths") or {}).items():
        for verb, op in (item or {}).items():
            if verb not in METHODS or not isinstance(op, dict):
                continue
            flow_name = op.get("operationId") or f"{verb}{pascal(path)}"
            flows.append(f"""
      <Flow name="{escape(flow_name)}">
        <Description>{escape(op.get('summary', ''))}</Description>
        <Request/>
        <Response/>
        <Condition>{escape(flow_condition(path, verb))}</Condition>
      </Flow>""")
    flows.append("""
      <Flow name="NotFound">
        <Request>
          <Step><Name>RF-NotFound</Name></Step>
        </Request>
        <Response/>
      </Flow>""")

    write(os.path.join(root, f"{name}.xml"), f"""
<APIProxy name="{escape(name)}">
  <Description>{escape(spec.get('info', {}).get('title', name))} - generated from OpenAPI spec</Description>
  <BasePaths>{escape(base_path)}</BasePaths>
</APIProxy>""")

    write(os.path.join(root, "proxies", "default.xml"), f"""
<ProxyEndpoint name="default">
  <PreFlow name="PreFlow">
    <Request>
      <Step><Name>{auth_policy}</Name></Step>
      <Step><Name>SA-SpikeArrest</Name></Step>
    </Request>
    <Response/>
  </PreFlow>
  <Flows>{''.join(flows)}
  </Flows>
  <HTTPProxyConnection>
    <BasePath>{escape(base_path)}</BasePath>
  </HTTPProxyConnection>
  <RouteRule name="default">
    <TargetEndpoint>default</TargetEndpoint>
  </RouteRule>
</ProxyEndpoint>""")

    write(os.path.join(root, "targets", "default.xml"), f"""
<TargetEndpoint name="default">
  <HTTPTargetConnection>
    <URL>{escape(target)}</URL>
  </HTTPTargetConnection>
</TargetEndpoint>""")

    policies = os.path.join(root, "policies")
    if oauth:
        write(os.path.join(policies, "OAuth-VerifyToken.xml"), """
<OAuthV2 name="OAuth-VerifyToken">
  <Operation>VerifyAccessToken</Operation>
</OAuthV2>""")
    else:
        write(os.path.join(policies, "VerifyAPIKey.xml"), """
<VerifyAPIKey name="VerifyAPIKey">
  <APIKey ref="request.header.x-api-key"/>
</VerifyAPIKey>""")
    write(os.path.join(policies, "SA-SpikeArrest.xml"), f"""
<SpikeArrest name="SA-SpikeArrest">
  <Rate>{escape(rate)}</Rate>
</SpikeArrest>""")
    write(os.path.join(policies, "RF-NotFound.xml"), """
<RaiseFault name="RF-NotFound">
  <FaultResponse>
    <Set>
      <StatusCode>404</StatusCode>
      <ReasonPhrase>Not Found</ReasonPhrase>
      <Payload contentType="application/json">{"error":"Resource not found"}</Payload>
    </Set>
  </FaultResponse>
</RaiseFault>""")

    zip_base = os.path.join(WORK_DIR, f"{name}-proxy")
    shutil.make_archive(zip_base, "zip", os.path.dirname(root))

    summary = "\n".join([
        "### What you'll get",
        f"- **Proxy name:** `{name}`",
        f"- **Gateway path:** `{base_path}`",
        f"- **Backend:** `{target}`",
        f"- **Security:** {'OAuth 2.0 access token' if oauth else 'API key in the `x-api-key` header'}",
        f"- **Rate limit:** `{rate}`",
        f"- **Operations mapped:** {len(flows) - 1} (anything else returns 404)",
    ])
    write(os.path.join(WORK_DIR, "proxy.md"), summary)
    print(summary)
    set_output("bundle_dir", os.path.dirname(root))


if __name__ == "__main__":
    main()
