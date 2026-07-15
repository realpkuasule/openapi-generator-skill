from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TEST_SOURCE = r'''package openapi

import (
    "bytes"
    "context"
    "encoding/json"
    "io"
    "os"
    "strings"
    "testing"
)

func TestEmpiricalContractFixture(t *testing.T) {
    pet := Pet{Id: 7, Name: "Milo", Status: "available"}
    encodedPet, err := json.Marshal(pet)
    if err != nil || !strings.Contains(string(encodedPet), `"name":"Milo"`) {
        t.Fatalf("pet serialization failed: %s %v", encodedPet, err)
    }

    problem := Problem{Title: "Not found", Status: 404}
    encodedProblem, err := json.Marshal(problem)
    if err != nil || !strings.Contains(string(encodedProblem), `"status":404`) {
        t.Fatalf("problem serialization failed: %s %v", encodedProblem, err)
    }

    ctx := context.WithValue(
        context.Background(),
        ContextAPIKeys,
        map[string]APIKey{"ApiKeyAuth": {Key: "fixture-key"}},
    )
    if ctx.Value(ContextAPIKeys) == nil {
        t.Fatal("API key context was not retained")
    }

    version, err := os.ReadFile(".openapi-generator/VERSION")
    if err != nil {
        t.Fatalf("generator version metadata is unreadable: %v", err)
    }
    if strings.HasPrefix(string(version), "7.23.") {
        client := NewAPIClient(NewConfiguration())
        input := []byte{0xff, 0x00, 0x42}
        var raw []byte
        if err := client.decode(&raw, input, "application/octet-stream"); err != nil || !bytes.Equal(raw, input) {
            t.Fatalf("raw byte decoding failed: %v %v", raw, err)
        }
        var reader io.Reader
        if err := client.decode(&reader, input, "application/octet-stream"); err != nil {
            t.Fatalf("reader decoding failed: %v", err)
        }
        decoded, err := io.ReadAll(reader)
        if err != nil || !bytes.Equal(decoded, input) {
            t.Fatalf("reader content differs: %v %v", decoded, err)
        }
    }
}
'''


def main() -> int:
    output = Path(sys.argv[1]).resolve()
    if not (output / "go.mod").is_file():
        raise SystemExit("generated Go module is missing")
    fixture = output / "empirical_fixture_test.go"
    fixture.write_text(TEST_SOURCE, encoding="utf-8")
    try:
        result = subprocess.run(
            ["go", "-C", str(output), "test", "."],
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fixture.unlink(missing_ok=True)
    if result.returncode:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:], file=sys.stderr)
    else:
        print("Go serialization, error-model, and API-key fixtures passed.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
