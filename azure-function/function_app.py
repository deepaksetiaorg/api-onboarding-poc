"""Azure Function (Python v2 model): receives the ADO service hook and triggers GitHub."""
import json
import logging

import azure.functions as func

from handler import handle

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="ado-intake", methods=["POST"])
def ado_intake(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse("body must be JSON", status_code=400)
    try:
        status, message = handle(req.headers.get("Authorization"), payload)
    except Exception as err:  # GitHub down, bad token, etc. 5xx makes ADO retry.
        logging.exception("dispatch failed")
        return func.HttpResponse(f"dispatch failed: {err}", status_code=502)
    logging.info(message)
    return func.HttpResponse(json.dumps({"message": message}), status_code=status, mimetype="application/json")
