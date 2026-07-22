"""Parity tests for the dynamic report JSON parser (ported from web/tests/dynamic.test.ts)."""

import json

from satori_cli.utils.parsers.dynamic import (
    dynamic_severity_to_template,
    parse_dynamic_output,
)


def test_returns_null_for_empty_stdout():
    assert parse_dynamic_output("") is None
    assert parse_dynamic_output(None) is None


def test_returns_null_for_plain_text_and_ansi_logs():
    assert parse_dynamic_output("some plain log output\nmore text") is None
    assert parse_dynamic_output("[32mOK[0m all tests passed") is None


def test_returns_null_for_uninformative_json():
    assert parse_dynamic_output("{}") is None
    assert parse_dynamic_output("[]") is None
    assert parse_dynamic_output('"a string"') is None
    assert parse_dynamic_output("42") is None
    assert parse_dynamic_output("true") is None
    assert parse_dynamic_output("null") is None
    assert parse_dynamic_output("[1, 2, 3]") is None
    assert parse_dynamic_output('{"ok": true}') is None


def test_returns_null_for_single_anonymous_field():
    assert parse_dynamic_output('[{"a": 1}]') is None


def test_returns_null_for_oversized_input():
    huge = "[" + '{"severity":"high","message":"x"},' * 70000 + "]"
    assert len(huge) > 2_000_000
    assert parse_dynamic_output(huge) is None


def test_parses_banner_wrapped_json():
    stdout = "\n".join(
        [
            "SomeTool v1.2.3 — the friendly scanner",
            "[+] scanning target...",
            json.dumps(
                {
                    "findings": [
                        {
                            "name": "Weak cipher enabled",
                            "severity": "high",
                            "target": "example.com:443",
                        },
                        {
                            "name": "Deprecated TLS version",
                            "severity": "medium",
                            "target": "example.com:443",
                        },
                    ]
                }
            ),
            "done in 2.3s",
        ]
    )
    findings = parse_dynamic_output(stdout)
    assert findings is not None
    assert len(findings) == 2
    assert findings[0].title == "Weak cipher enabled"
    assert findings[0].severity == "high"
    assert findings[0].location == "example.com:443"


SHELLCHECK_OUTPUT = [
    {
        "file": "myotherscript",
        "line": 2,
        "endLine": 2,
        "column": 1,
        "endColumn": 2,
        "level": "error",
        "code": 1035,
        "message": "You need a space after the [ and before the ].",
        "fix": None,
    },
    {
        "file": "myscript",
        "line": 2,
        "endLine": 2,
        "column": 6,
        "endColumn": 8,
        "level": "warning",
        "code": 2039,
        "message": "In POSIX sh, echo flags are undefined.",
        "fix": None,
    },
    {
        "file": "myscript",
        "line": 2,
        "endLine": 2,
        "column": 9,
        "endColumn": 11,
        "level": "info",
        "code": 2086,
        "message": "Double quote to prevent globbing and word splitting.",
        "fix": {
            "replacements": [
                {
                    "line": 2,
                    "endLine": 2,
                    "precedence": 7,
                    "insertionPoint": "afterEnd",
                    "column": 9,
                    "replacement": '"',
                    "endColumn": 9,
                },
                {
                    "line": 2,
                    "endLine": 2,
                    "precedence": 7,
                    "insertionPoint": "beforeStart",
                    "column": 11,
                    "replacement": '"',
                    "endColumn": 11,
                },
            ]
        },
    },
]


def test_shellcheck_binds_slots_and_sorts_severity():
    findings = parse_dynamic_output(json.dumps(SHELLCHECK_OUTPUT))
    assert findings is not None
    assert len(findings) == 3
    assert findings[0].title == "You need a space after the [ and before the ]."
    assert findings[0].severity == "error"
    assert findings[0].id == "1035"
    assert findings[0].location == "myotherscript"
    assert findings[0].line == 2
    assert findings[0].fields["column"] == "1"
    assert findings[1].severity == "warning"
    assert findings[2].severity == "info"


def test_shellcheck_summarizes_nested_object_arrays():
    findings = parse_dynamic_output(json.dumps(SHELLCHECK_OUTPUT))
    assert findings[2].fields["fix.replacements"] == "[2 items]"


HADOLINT_OUTPUT = [
    {
        "line": 9,
        "code": "DL3008",
        "message": (
            "Pin versions in apt get install. Instead of `apt-get install <package>` "
            "use `apt-get install <package>=<version>`"
        ),
        "column": 1,
        "file": "django-DefectDojo\\Dockerfile.django",
        "level": "warning",
    },
    {
        "line": 9,
        "code": "DL3015",
        "message": "Avoid additional packages by specifying `--no-install-recommends`",
        "column": 1,
        "file": "django-DefectDojo\\Dockerfile.django",
        "level": "info",
    },
    {
        "line": 44,
        "code": "DL3013",
        "message": (
            "Pin versions in pip. Instead of `pip install <package>` "
            "use `pip install <package>==<version>`"
        ),
        "column": 1,
        "file": "django-DefectDojo\\Dockerfile.django",
        "level": "warning",
    },
    {
        "line": 57,
        "code": "DL3006",
        "message": "Always tag the version of an image explicitly",
        "column": 1,
        "file": "django-DefectDojo\\Dockerfile.nginx",
        "level": "warning",
    },
]


def test_hadolint_parses_dl_codes_and_levels():
    findings = parse_dynamic_output(json.dumps(HADOLINT_OUTPUT))
    assert findings is not None
    assert len(findings) == 4
    assert [f.id for f in findings] == ["DL3008", "DL3013", "DL3006", "DL3015"]
    assert findings[0].title == (
        "Pin versions in apt get install. Instead of `apt-get install <package>` "
        "use `apt-get install <package>=<version>`"
    )
    assert findings[0].severity == "warning"
    assert findings[0].location == "django-DefectDojo\\Dockerfile.django"
    assert findings[0].line == 9


GOSEC_OUTPUT = {
    "Golang errors": {},
    "Issues": [
        {
            "severity": "HIGH",
            "confidence": "LOW",
            "cwe": {
                "id": "295",
                "url": "https://cwe.mitre.org/data/definitions/295.html",
            },
            "rule_id": "G402",
            "details": "TLS InsecureSkipVerify may be true.",
            "file": (
                "/Users/pascal/Documents/git/netweave/internal/smo/adapters/"
                "onap/client_aai.go"
            ),
            "code": (
                "302: \ttlsConfig := &tls.Config{\n"
                "303: \t\tInsecureSkipVerify: config.TLSInsecureSkipVerify,\n"
                "304: \t\tMinVersion:         tls.VersionTLS12,\n"
            ),
            "line": "303",
            "column": "23",
            "nosec": False,
            "suppressions": None,
        },
        {
            "severity": "MEDIUM",
            "confidence": "HIGH",
            "cwe": {
                "id": "22",
                "url": "https://cwe.mitre.org/data/definitions/22.html",
            },
            "rule_id": "G304",
            "details": "Potential file inclusion via variable",
            "file": "/Users/pascal/Documents/git/netweave/cmd/gateway/main.go",
            "code": (
                "534: \t\t// G304: path is from hardcoded list above, not user "
                "input - safe from path traversal\n"
                "535: \t\tdata, err := os.ReadFile(path)\n"
                "536: \t\tif err == nil {\n"
            ),
            "line": "535",
            "column": "16",
            "nosec": False,
            "suppressions": None,
            "autofix": (
                "Consider using os.Root to scope file access under a fixed root "
                "(Go >=1.24). Prefer root.Open/root.Stat over os.Open/os.Stat to "
                "prevent directory traversal."
            ),
        },
    ],
    "Stats": {"files": 128, "lines": 42010, "nosec": 1, "found": 5},
    "GosecVersion": "dev",
}


def test_gosec_picks_issues_and_binds_rule_id():
    findings = parse_dynamic_output(json.dumps(GOSEC_OUTPUT))
    assert findings is not None
    assert len(findings) == 2
    assert findings[0].title == "G402"
    assert findings[0].severity == "HIGH"
    assert findings[0].id == "G402"
    assert findings[0].location == (
        "/Users/pascal/Documents/git/netweave/internal/smo/adapters/onap/client_aai.go"
    )
    assert findings[0].line == 303
    assert findings[0].description == "TLS InsecureSkipVerify may be true."
    assert findings[0].url == "https://cwe.mitre.org/data/definitions/295.html"
    assert findings[0].fields["cwe.id"] == "295"
    assert findings[0].fields["confidence"] == "LOW"


def test_gosec_merges_root_primitives_as_context():
    findings = parse_dynamic_output(json.dumps(GOSEC_OUTPUT))
    assert findings[0].fields["GosecVersion"] == "dev"


def test_gosec_parses_numeric_string_line_numbers():
    findings = parse_dynamic_output(json.dumps(GOSEC_OUTPUT))
    assert findings[1].line == 535
    assert "os.Root" in findings[1].fields["autofix"]


GRYPE_OUTPUT = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2004-0971",
                "dataSource": "https://security-tracker.debian.org/tracker/CVE-2004-0971",
                "namespace": "debian:10",
                "severity": "Negligible",
                "urls": [
                    "https://security-tracker.debian.org/tracker/CVE-2004-0971"
                ],
                "fix": {"versions": [], "state": "not-fixed"},
            },
            "relatedVulnerabilities": [
                {
                    "id": "CVE-2004-0971",
                    "dataSource": "https://nvd.nist.gov/vuln/detail/CVE-2004-0971",
                    "namespace": "nvd",
                    "severity": "Low",
                    "description": (
                        "The krb5-send-pr script in the kerberos5 (krb5) package in "
                        "Trustix Secure Linux 1.5 through 2.1, and possibly other "
                        "operating systems, allows local users to ove"
                    ),
                    "urls": ["http://www.securityfocus.com/bid/11289"],
                }
            ],
            "matchDetails": [{"type": None, "matcher": "dpkg-matcher"}],
            "artifact": {
                "name": "libgssapi-krb5-2",
                "version": "1.17-3+deb10u3",
                "type": "deb",
                "language": "",
                "purl": "pkg:deb/debian/libgssapi-krb5-2@1.17-3+deb10u3?arch=amd64",
            },
        },
        {
            "vulnerability": {
                "id": "CVE-2021-32626",
                "dataSource": "https://nvd.nist.gov/vuln/detail/CVE-2021-32626",
                "namespace": "nvd",
                "severity": "High",
                "description": (
                    "Redis is an open source, in-memory database that persists on "
                    "disk. In affected versions specially crafted Lua scripts "
                    "executing in Redis can cause the heap-base"
                ),
                "urls": [
                    "https://github.com/redis/redis/commit/"
                    "666ed7facf4524bf6d19b11b20faa2cf93fdf591"
                ],
                "fix": {"versions": ["6.2.1"], "state": "wont-fix"},
            },
            "relatedVulnerabilities": [],
            "matchDetails": [{"type": None, "matcher": "python-matcher"}],
            "artifact": {
                "name": "redis",
                "version": "4.0.2",
                "type": "python",
                "language": "python",
                "purl": "pkg:pypi/redis@4.0.2",
            },
        },
        {
            "vulnerability": {
                "id": "CVE-2021-33574",
                "dataSource": (
                    "https://security-tracker.debian.org/tracker/CVE-2021-33574"
                ),
                "namespace": "debian:10",
                "severity": "Critical",
                "urls": [
                    "https://security-tracker.debian.org/tracker/CVE-2021-33574"
                ],
                "fix": {"versions": [], "state": "wont-fix"},
            },
            "relatedVulnerabilities": [
                {
                    "id": "CVE-2021-33574",
                    "dataSource": "https://nvd.nist.gov/vuln/detail/CVE-2021-33574",
                    "namespace": "nvd",
                    "severity": "Critical",
                    "description": (
                        "The mq_notify function in the GNU C Library (aka glibc) "
                        "versions 2.32 and 2.33 has a use-after-free. It may use "
                        "the notification thread attributes object (passe"
                    ),
                    "urls": [
                        "https://sourceware.org/bugzilla/show_bug.cgi?id=27896"
                    ],
                }
            ],
            "matchDetails": [{"type": None, "matcher": "dpkg-matcher"}],
            "artifact": {
                "name": "libc-bin",
                "version": "2.28-10",
                "type": "deb",
                "language": "",
                "purl": "pkg:deb/debian/libc-bin@2.28-10?arch=amd64",
            },
        },
    ],
    "source": {"type": "image"},
    "distro": {"name": "debian", "version": "10"},
    "descriptor": {"name": "grype", "version": "0.28.0"},
}


def test_grype_picks_matches_and_sorts_worst_first():
    findings = parse_dynamic_output(json.dumps(GRYPE_OUTPUT))
    assert findings is not None
    assert len(findings) == 3
    assert [f.severity for f in findings] == ["Critical", "High", "Negligible"]
    assert findings[0].title == "libc-bin"
    assert findings[0].id == "CVE-2021-33574"
    assert (
        findings[0].url
        == "https://security-tracker.debian.org/tracker/CVE-2021-33574"
    )
    assert findings[0].fields["relatedVulnerabilities"] == "[1 items]"
    assert "Redis is an open source" in findings[1].description


ESLINT_OUTPUT = [
    {
        "filePath": "/var/lib/jenkins/workspace/eslint Release/eslint/fullOfProblems.js",
        "messages": [
            {
                "ruleId": "no-unused-vars",
                "severity": 2,
                "message": "'addOne' is defined but never used.",
                "line": 1,
                "column": 10,
                "nodeType": "Identifier",
                "messageId": "unusedVar",
                "endLine": 1,
                "endColumn": 16,
            },
            {
                "ruleId": "use-isnan",
                "severity": 2,
                "message": "Use the isNaN function to compare with NaN.",
                "line": 2,
                "column": 9,
                "nodeType": "BinaryExpression",
                "messageId": "comparisonWithNaN",
                "endLine": 2,
                "endColumn": 17,
            },
            {
                "ruleId": "semi",
                "severity": 1,
                "message": "Missing semicolon.",
                "line": 3,
                "column": 20,
                "nodeType": "ReturnStatement",
                "messageId": "missingSemi",
                "endLine": 4,
                "endColumn": 1,
                "fix": {"range": [60, 60], "text": ";"},
            },
            {
                "ruleId": "consistent-return",
                "severity": 2,
                "message": "Function 'addOne' expected a return value.",
                "line": 5,
                "column": 7,
                "nodeType": "ReturnStatement",
                "messageId": "missingReturnValue",
                "endLine": 5,
                "endColumn": 13,
            },
        ],
        "suppressedMessages": [],
        "errorCount": 5,
        "fatalErrorCount": 0,
        "warningCount": 4,
        "fixableErrorCount": 2,
        "fixableWarningCount": 4,
        "source": (
            "function addOne(i) {\n    if (i != NaN) {\n        return i ++\n"
            "    } else {\n      return\n    }\n};"
        ),
    },
    {
        "filePath": "/path/to/a/file.js",
        "messages": [
            {
                "ruleId": "curly",
                "severity": 2,
                "message": "Expected { after 'if' condition.",
                "line": 2,
                "column": 1,
            },
            {
                "ruleId": "no-process-exit",
                "severity": 2,
                "message": "Don't use process.exit(); throw an error instead.",
                "line": 3,
                "column": 1,
            },
        ],
        "errorCount": 2,
        "warningCount": 0,
        "fixableErrorCount": 0,
        "fixableWarningCount": 0,
        "source": (
            "var err = doStuff();\n"
            "if (err) console.log('failed tests: ' + err);\n"
            "process.exit(1);\n"
        ),
    },
    {
        "filePath": "/path/to/Gruntfile.js",
        "messages": [],
        "errorCount": 0,
        "warningCount": 0,
        "fixableErrorCount": 0,
        "fixableWarningCount": 0,
    },
]


def test_eslint_explodes_messages_with_parent_filepath():
    findings = parse_dynamic_output(json.dumps(ESLINT_OUTPUT))
    assert findings is not None
    assert len(findings) == 6
    assert findings[0].title == "'addOne' is defined but never used."
    assert findings[0].id == "no-unused-vars"
    assert findings[0].location == (
        "/var/lib/jenkins/workspace/eslint Release/eslint/fullOfProblems.js"
    )
    assert findings[0].line == 1
    assert findings[0].severity == "2"
    assert findings[0].fields["errorCount"] == "5"
    assert findings[4].title == "Expected { after 'if' condition."
    assert findings[4].location == "/path/to/a/file.js"


def test_eslint_keeps_order_when_numeric_severities_unmapped():
    findings = parse_dynamic_output(json.dumps(ESLINT_OUTPUT))
    assert [f.id for f in findings] == [
        "no-unused-vars",
        "use-isnan",
        "semi",
        "consistent-return",
        "curly",
        "no-process-exit",
    ]
    assert dynamic_severity_to_template(findings[0].severity) is None


NPM_AUDIT_OUTPUT = {
    "auditReportVersion": 2,
    "vulnerabilities": {
        "copy-webpack-plugin": {
            "name": "copy-webpack-plugin",
            "severity": "moderate",
            "isDirect": True,
            "via": ["fast-glob", "globby"],
            "effects": [],
            "range": ">=6.0.0",
            "nodes": ["node_modules/copy-webpack-plugin"],
            "fixAvailable": {
                "name": "copy-webpack-plugin",
                "version": "6.0.0",
                "isSemVerMajor": True,
            },
        },
        "fast-glob": {
            "name": "fast-glob",
            "severity": "moderate",
            "isDirect": False,
            "via": ["micromatch"],
            "effects": ["copy-webpack-plugin", "globby"],
            "range": "*",
            "nodes": ["node_modules/fast-glob"],
            "fixAvailable": {
                "name": "copy-webpack-plugin",
                "version": "6.0.0",
                "isSemVerMajor": True,
            },
        },
        "micromatch": {
            "name": "micromatch",
            "severity": "moderate",
            "isDirect": False,
            "via": [
                {
                    "source": 1098615,
                    "name": "micromatch",
                    "dependency": "micromatch",
                    "title": "Regular Expression Denial of Service (ReDoS) in micromatch",
                    "url": "https://github.com/advisories/GHSA-952p-6rrq-rcjv",
                    "severity": "moderate",
                    "cwe": ["CWE-1333"],
                    "cvss": {"score": 0, "vectorString": None},
                    "range": "<=4.0.7",
                }
            ],
            "effects": ["fast-glob"],
            "range": "*",
            "nodes": ["node_modules/micromatch"],
            "fixAvailable": {
                "name": "copy-webpack-plugin",
                "version": "6.0.0",
                "isSemVerMajor": True,
            },
        },
    },
    "metadata": {
        "vulnerabilities": {
            "info": 0,
            "low": 0,
            "moderate": 4,
            "high": 0,
            "critical": 0,
            "total": 4,
        },
        "dependencies": {
            "prod": 317,
            "dev": 0,
            "optional": 12,
            "peer": 0,
            "peerOptional": 0,
            "total": 329,
        },
    },
}


def test_npm_audit_homogeneous_object_map():
    findings = parse_dynamic_output(json.dumps(NPM_AUDIT_OUTPUT))
    assert findings is not None
    assert len(findings) == 3
    assert findings[0].title == "copy-webpack-plugin"
    assert findings[0].severity == "moderate"
    assert dynamic_severity_to_template(findings[0].severity) == "MEDIUM"
    assert findings[0].fields["key"] == "copy-webpack-plugin"
    assert findings[0].fields["auditReportVersion"] == "2"
    assert findings[0].fields["via"] == "fast-glob, globby"
    assert findings[2].fields["via"] == "[1 items]"
    assert findings[0].fields["fixAvailable.version"] == "6.0.0"


ZAP_OUTPUT = {
    "@programName": "OWASP ZAP",
    "@version": "2.12.0",
    "@generated": "Sat, 15 Apr 2023 18:23:09",
    "site": [
        {
            "@name": "https://example-backend.example.com",
            "@host": "example-backend.example.com",
            "@port": "443",
            "@ssl": "true",
            "alerts": [
                {
                    "pluginid": "10098",
                    "alertRef": "10098",
                    "alert": "Cross-Domain Misconfiguration",
                    "name": "Cross-Domain Misconfiguration",
                    "riskcode": "2",
                    "confidence": "2",
                    "riskdesc": "Medium (Medium)",
                    "desc": (
                        "<p>Web browser data loading may be possible, due to a "
                        "Cross Origin Resource Sharing (CORS) misconfiguration on</p>"
                    ),
                    "instances": [
                        {
                            "uri": (
                                "https://example-backend.example.com/django-static/"
                                "admin/css/base.css"
                            ),
                            "method": "GET",
                            "param": "",
                            "attack": "",
                            "evidence": "Access-Control-Allow-Origin: *",
                            "otherinfo": (
                                "The CORS misconfiguration on the web server "
                                "permits cross-do"
                            ),
                        },
                        {
                            "uri": (
                                "https://example-backend.example.com/django-static/"
                                "admin/css/login.css"
                            ),
                            "method": "GET",
                            "param": "",
                            "attack": "",
                            "evidence": "Access-Control-Allow-Origin: *",
                            "otherinfo": (
                                "The CORS misconfiguration on the web server "
                                "permits cross-do"
                            ),
                        },
                    ],
                    "count": "2",
                    "solution": (
                        "<p>Ensure that sensitive data is not available in an "
                        "unauthenticated manner (using IP address white-listing, f</p>"
                    ),
                    "otherinfo": (
                        "<p>The CORS misconfiguration on the web server permits "
                        "cross-domain read requests from arbitrary third party d</p>"
                    ),
                    "reference": (
                        "<p>https://vulncat.fortify.com/en/detail?id=desc.config."
                        "dotnet.html5_overly_permissive_cors_policy</p>"
                    ),
                    "cweid": "264",
                    "wascid": "14",
                    "sourceid": "31",
                },
                {
                    "pluginid": "10027",
                    "alertRef": "10027",
                    "alert": "Information Disclosure - Suspicious Comments",
                    "name": "Information Disclosure - Suspicious Comments",
                    "riskcode": "0",
                    "confidence": "1",
                    "riskdesc": "Informational (Low)",
                    "desc": (
                        "<p>The response appears to contain suspicious comments "
                        "which may help an attacker. Note: Matches made within s</p>"
                    ),
                    "instances": [
                        {
                            "uri": "https://example-backend.example.com/admin/",
                            "method": "GET",
                            "param": "",
                            "attack": "",
                            "evidence": "admin",
                            "otherinfo": (
                                "The following pattern was used: \\bADMIN\\b and "
                                "was detected i"
                            ),
                        }
                    ],
                    "count": "1",
                    "solution": (
                        "<p>Remove all comments that return information that may "
                        "help an attacker and fix any underlying problems they</p>"
                    ),
                    "otherinfo": (
                        '<p>The following pattern was used: \\bADMIN\\b and was '
                        'detected in the element starting with: "<script src="/dja</p>'
                    ),
                    "reference": "",
                    "cweid": "200",
                    "wascid": "13",
                    "sourceid": "1",
                },
                {
                    "pluginid": "10049",
                    "alertRef": "10049",
                    "alert": "Non-Storable Content",
                    "name": "Non-Storable Content",
                    "riskcode": "0",
                    "confidence": "2",
                    "riskdesc": "Informational (Medium)",
                    "desc": (
                        "<p>The response contents are not storable by caching "
                        "components such as proxy servers. If the response does no</p>"
                    ),
                    "instances": [
                        {
                            "uri": "https://example-backend.example.com/",
                            "method": "GET",
                            "param": "",
                            "attack": "",
                            "evidence": "no-store",
                            "otherinfo": "",
                        }
                    ],
                    "count": "1",
                    "solution": (
                        "<p>The content may be marked as storable by ensuring that "
                        "the following conditions are satisfied:</p><p>The re</p>"
                    ),
                    "otherinfo": "",
                    "reference": (
                        "<p>https://tools.ietf.org/html/rfc7234</p>"
                        "<p>https://tools.ietf.org/html/rfc7231</p>"
                        "<p>http://www.w3.org/Proto</p>"
                    ),
                    "cweid": "524",
                    "wascid": "13",
                    "sourceid": "4",
                },
            ],
        }
    ],
}


def test_zap_picks_alerts_and_binds_riskdesc():
    findings = parse_dynamic_output(json.dumps(ZAP_OUTPUT))
    assert findings is not None
    assert len(findings) == 3
    assert findings[0].title == "Cross-Domain Misconfiguration"
    assert findings[0].severity == "Medium (Medium)"
    assert findings[0].id == "10098"
    assert findings[0].location == "example-backend.example.com"
    assert dynamic_severity_to_template(findings[0].severity) == "MEDIUM"
    assert dynamic_severity_to_template(findings[1].severity) == "INFO"
    assert findings[0].fields["riskcode"] == "2"
    assert findings[0].fields["instances"] == "[2 items]"
    assert findings[0].fields["@port"] == "443"
    assert findings[0].fields["@programName"] == "OWASP ZAP"


HTTPX_OUTPUT = "\n".join(
    [
        (
            '{"timestamp":"2024-07-08T22:09:49.294748+01:00","port":"80",'
            '"url":"http://google.co.uk:80","input":"http://google.co.uk:80",'
            '"location":"http://www.google.co.uk/","title":"301 Moved",'
            '"scheme":"http","webserver":"gws","content_type":"text/html",'
            '"method":"GET","path":"/","time":"37.977542ms",'
            '"a":["172.217.169.35"],"aaaa":["2a00:1450:4009:822::2003"],'
            '"tech":["Google Web Server"],"words":9,"lines":6,"status_code":301,'
            '"content_length":221,"failed":false,'
            '"knowledgebase":{"PageType":"error","pHash":0},'
            '"resolvers":["1.1.1.1:53","1.0.0.1:53"]}'
        ),
        (
            '{"timestamp":"2024-06-07T14:07:44.854709513+01:00","port":"80",'
            '"url":"http://44.217.71.211:80","input":"http://44.217.71.211:80",'
            '"scheme":"http","webserver":"awselb/2.0","content_type":"text/html",'
            '"method":"GET","path":"/","time":"350.934693ms",'
            '"a":["44.217.71.211"],'
            '"tech":["Amazon ELB","Amazon Web Services","PHP:8.1.4"],'
            '"words":8,"lines":1,"content_length":91,"failed":false,'
            '"knowledgebase":{"PageType":"nonerror","pHash":0}}'
        ),
    ]
)


def test_httpx_jsonl_parsing():
    findings = parse_dynamic_output(HTTPX_OUTPUT)
    assert findings is not None
    assert len(findings) == 2
    assert findings[0].title == "301 Moved"
    assert findings[0].url == "http://google.co.uk:80"
    assert findings[0].severity is None
    assert findings[0].fields["tech"] == "Google Web Server"
    assert findings[0].fields["webserver"] == "gws"
    assert findings[0].fields["knowledgebase.PageType"] == "error"
    assert findings[0].fields["status_code"] == "301"
    assert findings[0].line is None


def test_httpx_title_fallback_skips_timestamp():
    findings = parse_dynamic_output(HTTPX_OUTPUT)
    assert findings[1].title == "http://44.217.71.211:80"


SUBFINDER_OUTPUT = "\n".join(
    [
        '{"host":"www.hackerone.com","input":"hackerone.com","source":"alienvault"}',
        '{"host":"docs.hackerone.com","input":"hackerone.com","source":"crtsh"}',
        '{"host":"api.hackerone.com","input":"hackerone.com","source":"hackertarget"}',
    ]
)


def test_subfinder_sparse_jsonl():
    findings = parse_dynamic_output(SUBFINDER_OUTPUT)
    assert findings is not None
    assert len(findings) == 3
    assert findings[0].location == "www.hackerone.com"
    assert findings[0].fields["source"] == "alienvault"


def test_jsonl_with_interleaved_log_lines():
    stdout = "\n".join(
        [
            "starting probe v3.1",
            '{"host":"a.example.com","severity":"high","issue":"expired certificate"}',
            '{"host":"b.example.com","severity":"low","issue":"self-signed certificate"}',
            '{"host":"c.example.com","severity":"low","issue":"weak key"}',
            '{"host":"d.example.com","severity":"info","issue":"ok"}',
            '{"host":"e.example.com","severity":"info","issue":"ok"}',
        ]
    )
    findings = parse_dynamic_output(stdout)
    assert findings is not None
    assert len(findings) == 5
    assert findings[0].title == "expired certificate"
    assert findings[0].severity == "high"
    assert findings[0].location == "a.example.com"


def test_dynamic_severity_to_template_word_map():
    assert dynamic_severity_to_template("blocker") == "BLOCKER"
    assert dynamic_severity_to_template("CRITICAL") == "CRITICAL"
    assert dynamic_severity_to_template("crit") == "CRITICAL"
    assert dynamic_severity_to_template("fatal") == "CRITICAL"
    assert dynamic_severity_to_template("High") == "HIGH"
    assert dynamic_severity_to_template("error") == "HIGH"
    assert dynamic_severity_to_template("severe") == "HIGH"
    assert dynamic_severity_to_template("important") == "HIGH"
    assert dynamic_severity_to_template("medium") == "MEDIUM"
    assert dynamic_severity_to_template("moderate") == "MEDIUM"
    assert dynamic_severity_to_template("warning") == "MEDIUM"
    assert dynamic_severity_to_template("warn") == "MEDIUM"
    assert dynamic_severity_to_template("low") == "LOW"
    assert dynamic_severity_to_template("minor") == "LOW"
    assert dynamic_severity_to_template("info") == "INFO"
    assert dynamic_severity_to_template("informational") == "INFO"
    assert dynamic_severity_to_template("note") == "INFO"
    assert dynamic_severity_to_template("style") == "INFO"
    assert dynamic_severity_to_template("none") == "INFO"
    assert dynamic_severity_to_template("negligible") == "INFO"


def test_dynamic_severity_to_template_composite_and_numeric():
    assert dynamic_severity_to_template("High (Medium)") == "HIGH"
    assert dynamic_severity_to_template("3 (Medium)") == "MEDIUM"
    assert dynamic_severity_to_template("2") is None
    assert dynamic_severity_to_template("7.5") is None
    assert dynamic_severity_to_template("0") is None
    assert dynamic_severity_to_template(None) is None
    assert dynamic_severity_to_template("") is None
    assert dynamic_severity_to_template("unknown") is None
    assert dynamic_severity_to_template("constructor") is None
