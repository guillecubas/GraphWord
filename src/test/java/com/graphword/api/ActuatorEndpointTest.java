package com.graphword.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ActuatorEndpointTest {

    @LocalServerPort
    int port;

    @Autowired
    TestRestTemplate restTemplate;

    @Test
    void prometheusEndpointExposesApplicationMetrics() {
        String body = restTemplate.getForObject("http://localhost:" + port + "/actuator/prometheus", String.class);

        assertThat(body).contains("jvm_memory_used_bytes");
        assertThat(body).contains("http_server_requests_active_seconds");
    }
}
