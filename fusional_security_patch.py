_SECURITY_CANDIDATES = [
    # Same repo layout: mcp-consulting-kit/showcase-servers/common
    Path(__file__).resolve().parents[2] / "mcp-consulting-kit" / "showcase-servers" / "common",
    Path(__file__).resolve().parents[3] / "mcp-consulting-kit" / "showcase-servers" / "common",
    # Sibling common/ directory
    Path(__file__).resolve().parent / "common",
    # Home directory layouts (Linux/Mac/Windows)
    Path.home() / "Projects" / "mcp-consulting-kit" / "showcase-servers" / "common",
    Path.home() / "mcp-consulting-kit" / "showcase-servers" / "common",
    Path.home() / "projects" / "mcp-consulting-kit" / "showcase-servers" / "common",
]
