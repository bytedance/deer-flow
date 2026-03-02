import os
import json
from mitmproxy import http

class FlowSaver:
    def __init__(self):
        # Create a directory to store the files
        self.save_dir = "saved_flows"
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.counter = 0

    def parse_body(self, text):
        """Try to parse the body as JSON. If it fails, return as a raw string."""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def response(self, flow: http.HTTPFlow):
        """This triggers every time a response is fully received."""
        self.counter += 1

        req_filename = os.path.join(self.save_dir, f"{self.counter}_request.json")
        res_filename = os.path.join(self.save_dir, f"{self.counter}_response.json")

        # --- Prepare and Save the Request ---
        request_data = {
            "url": flow.request.url,
            "method": flow.request.method,
            "headers": dict(flow.request.headers),
            "body": self.parse_body(flow.request.get_text(strict=False))
        }

        with open(req_filename, "w", encoding="utf-8") as f:
            # ensure_ascii=False allows Unicode characters to be saved natively (not as \uXXXX)
            json.dump(request_data, f, indent=4, ensure_ascii=False)

        # --- Prepare and Save the Response ---
        response_data = {
            "status_code": flow.response.status_code,
            "headers": dict(flow.response.headers),
            "body": self.parse_body(flow.response.get_text(strict=False))
        }

        with open(res_filename, "w", encoding="utf-8") as f:
            json.dump(response_data, f, indent=4, ensure_ascii=False)

# Register the addon
addons = [FlowSaver()]