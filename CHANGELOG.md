# Changelog

## [0.1.4](https://github.com/dcc-mcp/dcc-mcp-speedtree/compare/v0.1.3...v0.1.4) (2026-11-27)


### Documentation

* clarify DCC-MCP brand and MIT attribution ([#20](https://github.com/dcc-mcp/dcc-mcp-speedtree/issues/20)) ([7064d4e](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/7064d4e2c4507ef7d514cdb571a2b9f0a79218eb))
* refresh the generated DCC-MCP host matrix pointer ([c5736c8](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/c5736c8e65a0330895b0b92b3f66ca4645e8c5fd))

## [0.1.3](https://github.com/dcc-mcp/dcc-mcp-speedtree/compare/v0.1.2...v0.1.3) (2026-11-19)


### Features

* add production tree visual diagnostics ([7437a0c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/7437a0c1ab64099c2bec5c1963b28102c327570e))
* add speedtree-live skill for background co-design in a running Modeler ([2ef9d1c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/2ef9d1c9dab2b2f5d59d3b833df877f68fb36973))
* enforce planar card geometry during reference fitting ([d6bac41](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/d6bac41b447c0862651b79d32440139e11fd2a01))
* fit tree parameters against references under constraints ([4cdf5b1](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/4cdf5b1126187e62621fcfafc37b97a985fe7c18))
* prepare reference-based production tree candidates ([409705c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/409705c3de209ae2fad7393580c70d2e40f8b0fa))


### Bug Fixes

* **live:** drive the Modeler through the trusted dcc-cua ui-control route ([25b6e99](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/25b6e99d15b0fc0f6bd18ae00cff2ac8d521e9f1))
* **live:** gate compensation on known dispatch, stop claiming unverified effects ([9b298fc](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/9b298fcdd818d5b7c2ed56c6cfca4ccb7e8a2cab))
* **live:** integrate guarded sessions with production tools ([fb02c6c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/fb02c6c9ada00bcae3f50be67c9d54b131878c76))
* **live:** refuse document-dependent actions before Save ([8d1de05](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/8d1de05684f97a7eb3c1ee6ccb12724ff753353d))
* **live:** refuse the dependent apply phase without a source-bound save ([f2ae45b](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/f2ae45b43a82305b082100e844620341c73320a6))
* **live:** refuse undelivered menu actions and keep backups on unverified reloads ([b2972de](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/b2972de8a895bdbff904e7e435053d60f81b9e47))
* **live:** refuse undo without a source-bound active-document path ([f45bcf9](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/f45bcf913ef5e721eafc81cc7036c3c22fc89c87))
* **live:** require proof for no-dispatch and for the save prerequisite ([74e8d92](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/74e8d92e6353f6577bcda439776b07f9ddee6f50))
* **production:** reject dependency aliases by file identity ([3c46b65](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/3c46b65ace44e6852fe0cea0f7e02ae26f5f0970))
* **production:** reject drive-less rooted dependencies ([cd1571c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/cd1571c102f0202a28d7eacb6dbe663822f8184b))
* **production:** reject Windows dependency path aliases ([0ec7297](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/0ec729789a60838b6fd02380ac48ea19463e924c))
* retain safe capture failure diagnostics ([0cd90f6](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/0cd90f6717bb428c5a7c6a47bcdc16d46534ffee))
* **validation:** bound shared-vertex traversal memory ([dd2d8b6](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/dd2d8b68021dc84d831cfaff0bcf5364168bc938))


### Documentation

* **live:** align published README, bootstrap contract and live catalog ([b76fda9](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/b76fda9952909e440793c80f00856875df585a6c))
* refresh the generated DCC-MCP host matrix pointer ([51dc1e9](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/51dc1e90b6e5f62b5112d84fe4dca67f0ebee5c7))

## [0.1.2](https://github.com/dcc-mcp/dcc-mcp-speedtree/compare/v0.1.1...v0.1.2) (2026-10-10)


### Bug Fixes

* hide background Modeler commands on Windows ([#8](https://github.com/dcc-mcp/dcc-mcp-speedtree/issues/8)) ([7bc8be3](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/7bc8be3792d8d448107803efa2cb4b85cb736af1))

## [0.1.1](https://github.com/dcc-mcp/dcc-mcp-speedtree/compare/v0.1.0...v0.1.1) (2026-09-27)


### Features

* add native generator graph authoring and showcase ([0f9e660](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/0f9e660208c4aa958c819f339dd4df2ec7368eb7))
* add official batch export and DCC handoff ([b0c8ac4](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/b0c8ac4b764b11d038c0b512ab203c079f1132f3))
* add SpeedTree DCC-MCP adapter ([25edcc9](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/25edcc90be2c32834a9626071c98b912e50803d3))
* discover official SpeedTree samples and presets ([a688230](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/a6882306a3ec6766ef165acce506995e0dd3364c))


### Bug Fixes

* expose capabilities and verify packaged tool contracts ([c7c168c](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/c7c168c81637e3b5b598f796c38ed4769ec1ff1e))


### Documentation

* show verified SpeedTree to Unreal workflow ([7d3136a](https://github.com/dcc-mcp/dcc-mcp-speedtree/commit/7d3136a344c12dcb0ba4d8c71d133a2140af0efe))
