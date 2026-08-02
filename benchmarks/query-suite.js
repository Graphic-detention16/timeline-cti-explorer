import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const tokenLatency = new Trend("token_search_duration", true);
const phraseLatency = new Trend("phrase_search_duration", true);
const baseUrl = __ENV.BASE_URL || "https://localhost:8443";
const apiKey = __ENV.API_KEY;

export const options = {
  insecureSkipTLSVerify: true,
  stages: [
    { duration: "5m", target: 10 },
    { duration: "30m", target: 10 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.001"],
    token_search_duration: ["p(95)<1000"],
    phrase_search_duration: ["p(95)<2000"],
  },
};

const tokenQueries = ["CVE exploit", "phishing infrastructure", "APT42", "ransomware campaign"];
const phraseQueries = ["remote code execution", "credential theft", "fidye yazılımı kampanyası"];

export default function () {
  const phrase = __ITER % 5 === 0;
  const querySet = phrase ? phraseQueries : tokenQueries;
  const query = querySet[__ITER % querySet.length];
  const mode = phrase ? "phrase" : "all";
  const response = http.get(
    `${baseUrl}/api/v1/search?q=${encodeURIComponent(query)}&mode=${mode}&limit=100`,
    { headers: { Authorization: `Bearer ${apiKey}` }, tags: { mode } },
  );
  (phrase ? phraseLatency : tokenLatency).add(response.timings.duration);
  check(response, { "search returned 200": (result) => result.status === 200 });
  sleep(0.2);
}

