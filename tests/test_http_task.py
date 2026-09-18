"""Unit and integration tests for HTTPTask using a local mock HTTP server."""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FunctionTask,
    HTTPMethod,
    HTTPResult,
    HTTPTask,
    TaskStatus,
    Workflow,
)


class MockHTTPHandler(BaseHTTPRequestHandler):
    """Local HTTP handler for testing HTTPTask without internet access."""

    def log_message(self, format, *args):
        # Suppress standard logging during tests
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/hello":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {"message": "hello_from_mock", "query": query}
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif parsed.path == "/auth":
            auth_header = self.headers.get("Authorization", "")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"auth:{auth_header}".encode("utf-8"))

        elif parsed.path == "/slow":
            time.sleep(0.3)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"slow_done")
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass


        elif parsed.path == "/flaky":
            # Count visits via server attribute
            server: Any = self.server
            server.flaky_count += 1
            if server.flaky_count < 2:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Service Unavailable")
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Service Recovered")

        elif parsed.path == "/not_found":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Resource missing")

        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Bad Request")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        if self.path == "/submit":
            payload = json.loads(body) if body else {}
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {"status": "created", "received": payload}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class TestHTTPTask(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Start ephemeral local HTTP server
        cls.server = HTTPServer(("127.0.0.1", 0), MockHTTPHandler)
        cls.server.flaky_count = 0
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.engine = Engine(verbose=False)

    def test_get_request_with_query_params(self):
        task = HTTPTask(
            "FetchHello",
            url=f"{self.base_url}/hello",
            params={"user": "alice", "tier": "pro"},
        )
        wf = Workflow("Get WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        tr = result.get_task_result("FetchHello")
        http_res: HTTPResult = tr.output

        self.assertEqual(http_res.status_code, 200)
        self.assertTrue(http_res.is_success)
        payload = http_res.json()
        self.assertEqual(payload["message"], "hello_from_mock")
        self.assertEqual(payload["query"]["user"], ["alice"])
        self.assertEqual(payload["query"]["tier"], ["pro"])

    def test_post_json_payload(self):
        task = HTTPTask(
            "CreateItem",
            url=f"{self.base_url}/submit",
            method=HTTPMethod.POST,
            json_data={"item_id": 42, "title": "Widget"},
        )
        wf = Workflow("Post WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        http_res = result.get_task_result("CreateItem").output
        self.assertEqual(http_res.status_code, 201)
        self.assertEqual(http_res.json()["received"]["title"], "Widget")

    def test_upstream_data_flow_to_post(self):
        def generate_record():
            return {"sensor": "A1", "temperature": 24.5}

        t_gen = FunctionTask("GenRecord", fn=generate_record)
        t_http = HTTPTask(
            "PostRecord",
            url=f"{self.base_url}/submit",
            method=HTTPMethod.POST,
        )

        t_gen >> t_http

        wf = Workflow("Upstream HTTP WF").add_task(t_http)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        http_res = result.get_task_result("PostRecord").output
        self.assertEqual(http_res.status_code, 201)
        self.assertEqual(http_res.json()["received"]["sensor"], "A1")

    def test_authentication_headers(self):
        # Basic Auth
        t_basic = HTTPTask("BasicAuth", url=f"{self.base_url}/auth", auth=("forge_user", "secret"))
        wf1 = Workflow("Auth WF 1").add_task(t_basic)
        res1 = self.engine.run(wf1)
        self.assertTrue(res1.is_success)
        self.assertIn("Basic", res1.get_task_result("BasicAuth").output.body)

        # Bearer Token
        t_bearer = HTTPTask("BearerAuth", url=f"{self.base_url}/auth", bearer_token="my_token_123")
        wf2 = Workflow("Auth WF 2").add_task(t_bearer)
        res2 = self.engine.run(wf2)
        self.assertTrue(res2.is_success)
        self.assertIn("Bearer my_token_123", res2.get_task_result("BearerAuth").output.body)

    def test_allowed_status_codes(self):
        # 404 is allowed explicitly
        task = HTTPTask(
            "Allowed404",
            url=f"{self.base_url}/not_found",
            allowed_status_codes=[200, 404],
        )
        wf = Workflow("Allowed 404 WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Allowed404").output.status_code, 404)

    def test_status_code_failure(self):
        task = HTTPTask("Fail404", url=f"{self.base_url}/not_found")
        wf = Workflow("Fail 404 WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_failed)
        tr = result.get_task_result("Fail404")
        self.assertTrue(tr.is_failed)
        self.assertIn("failed with status 404", tr.error_message)

    def test_http_timeout(self):
        task = HTTPTask("SlowTask", url=f"{self.base_url}/slow", timeout=0.05)
        wf = Workflow("Timeout WF").add_task(task)

        start = time.perf_counter()
        result = self.engine.run(wf)
        elapsed = time.perf_counter() - start

        self.assertTrue(result.is_failed)
        tr = result.get_task_result("SlowTask")
        self.assertTrue(tr.is_failed)
        self.assertIn("timed out", tr.error_message)
        self.assertLess(elapsed, 0.4)

    def test_retry_on_flaky_endpoint(self):
        self.server.flaky_count = 0
        task = HTTPTask(
            "FlakyEndpoint",
            url=f"{self.base_url}/flaky",
            max_retries=2,
            retry_delay=0.01,
            failure_strategy=FailureStrategy.RETRY,
        )
        wf = Workflow("Flaky WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        tr = result.get_task_result("FlakyEndpoint")
        self.assertEqual(tr.attempt_count, 2)
        self.assertEqual(tr.output.status_code, 200)
        self.assertEqual(tr.output.body, "Service Recovered")


if __name__ == "__main__":
    unittest.main()
