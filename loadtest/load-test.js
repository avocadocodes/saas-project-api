import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "1m", target: 25 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

function authHeaders() {
  return {
    Authorization: `Bearer ${TOKEN}`,
    "Content-Type": "application/json",
  };
}

export function setup() {
  if (!TOKEN) {
    console.warn(
      "TOKEN env var is empty — set TOKEN=<jwt> before running or all requests will fail auth."
    );
  }
}

export default function () {
  const projectsRes = http.get(`${BASE_URL}/api/v1/projects/`, {
    headers: authHeaders(),
  });
  check(projectsRes, {
    "GET /projects/ is 200": (r) => r.status === 200,
  });

  const tasksRes = http.get(`${BASE_URL}/api/v1/tasks/`, {
    headers: authHeaders(),
  });
  check(tasksRes, {
    "GET /tasks/ is 200": (r) => r.status === 200,
  });

  // ~10% of iterations create a task
  if (Math.random() < 0.1) {
    const results = projectsRes.json("results");
    if (results && results.length > 0) {
      const projectId = results[0].id;
      const createRes = http.post(
        `${BASE_URL}/api/v1/tasks/`,
        JSON.stringify({
          project: projectId,
          title: `Load test task ${Date.now()}`,
          status: "TODO",
        }),
        { headers: authHeaders() }
      );
      check(createRes, {
        "POST /tasks/ is 201": (r) => r.status === 201,
      });
    }
  }

  sleep(1);
}
