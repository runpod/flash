# Changelog

## [1.1.1](https://github.com/runpod/flash/compare/v1.1.0...v1.1.1) (2026-02-09)


### Bug Fixes

* AE-2041: standardize cli cmd names ([#179](https://github.com/runpod/flash/issues/179)) ([9d035e3](https://github.com/runpod/flash/commit/9d035e3d1f43e3661f8ee11611070326b60379c5))

## [1.1.0](https://github.com/runpod/flash/compare/v1.0.0...v1.1.0) (2026-02-06)


### Features

* flash deploy auto builds, automatic app & env management ([#178](https://github.com/runpod/flash/issues/178)) ([cee5e74](https://github.com/runpod/flash/commit/cee5e74ea90d766933aba7adcf8ae55454dba9c2))
* improve deployment guidance and route discovery ([#181](https://github.com/runpod/flash/issues/181)) ([11681b5](https://github.com/runpod/flash/commit/11681b553aa6d05deb8169f7fd6e35e662c3afed))


### Performance Improvements

* fail build fast on size limit, remove blocking LB health check ([#182](https://github.com/runpod/flash/issues/182)) ([5278449](https://github.com/runpod/flash/commit/527844961a206fb6f7f656bc476a711896c001d9))

## [1.0.0](https://github.com/runpod/flash/compare/v0.25.1...v1.0.0) (2026-02-04)


### ⚠ BREAKING CHANGES

* rename tetra to flash ([#165](https://github.com/runpod/flash/issues/165))

### Bug Fixes

* 0.25.3 ([#173](https://github.com/runpod/flash/issues/173)) ([98b1ed7](https://github.com/runpod/flash/commit/98b1ed7c98ee8bbab43b4c880210579c1cab6a37))


### Code Refactoring

* rename tetra to flash ([#165](https://github.com/runpod/flash/issues/165)) ([7546eaf](https://github.com/runpod/flash/commit/7546eaf4e65cc828c46cf53b57ea41b8f7374d64))

## [0.25.1](https://github.com/runpod/runpod-flash/compare/v0.25.0...v0.25.1) (2026-02-03)


### Bug Fixes

* set build id for env before deploying resources ([#169](https://github.com/runpod/runpod-flash/issues/169)) ([e5d38d6](https://github.com/runpod/runpod-flash/commit/e5d38d61c6daf12a482341c5675b9125431f6d05))

## [0.25.0](https://github.com/runpod/runpod-flash/compare/v0.24.0...v0.25.0) (2026-02-02)


### Features

* `flash build --preview` in local docker for smoke-testing deployments ([#167](https://github.com/runpod/runpod-flash/issues/167)) ([a2cc56c](https://github.com/runpod/runpod-flash/commit/a2cc56c755ae6badb4f00ad8fe62c2e3d89af9bd))
* code intelligence indexer service for Claude Code ([#158](https://github.com/runpod/runpod-flash/issues/158)) ([69b3887](https://github.com/runpod/runpod-flash/commit/69b38875b9991d8e8095b39d98382f99487adfad))


### Bug Fixes

* exclude NetworkVolume from undeploy list command ([#164](https://github.com/runpod/runpod-flash/issues/164)) ([b0960d9](https://github.com/runpod/runpod-flash/commit/b0960d967b588b43c0970a42e8fa8c69c7e83077))


### Code Refactoring

* **build:** remove deprecated handler generator and add verification scripts ([#166](https://github.com/runpod/runpod-flash/issues/166)) ([5a253af](https://github.com/runpod/runpod-flash/commit/5a253af047052acdf1874072ddb8864bbdfa1679))
* rename archive.tar.gz to artifact.tar.gz ([#170](https://github.com/runpod/runpod-flash/issues/170)) ([1f033c3](https://github.com/runpod/runpod-flash/commit/1f033c39ec71f1291d5c261aa5d88bb0182c2270))

## [0.24.0](https://github.com/runpod/runpod-flash/compare/v0.23.1...v0.24.0) (2026-01-30)


### Features

* undeploy resources during flash deploy delete ([#155](https://github.com/runpod/runpod-flash/issues/155)) ([5256821](https://github.com/runpod/runpod-flash/commit/5256821c8698116b6b05c8f7b836cecfccf0d22f))

## [0.23.1](https://github.com/runpod/runpod-flash/compare/v0.23.0...v0.23.1) (2026-01-29)


### Bug Fixes

* add flash env id to saveendpoint during flash deploy ([#161](https://github.com/runpod/runpod-flash/issues/161)) ([d5c000e](https://github.com/runpod/runpod-flash/commit/d5c000e861d81a68cdb5f2426a989ebc3ddfc174))

## [0.23.0](https://github.com/runpod/runpod-flash/compare/v0.22.0...v0.23.0) (2026-01-29)


### Features

* disable EU-RO-1 lock in non production environments ([5f4772d](https://github.com/runpod/runpod-flash/commit/5f4772df988da5db54476cc9f14f71cb6727f516))
* pull in endpoint base from runpod-python ([a970406](https://github.com/runpod/runpod-flash/commit/a970406444af3db4a8232a4903d87332a2fd12ab))
* support specific GPU ids in serverless resource config ([#143](https://github.com/runpod/runpod-flash/issues/143)) ([86fde45](https://github.com/runpod/runpod-flash/commit/86fde45d64e3936a79d41be19321088f0e4f4c96))


### Bug Fixes

* **deploy:** apply CPU disk auto-sizing to load balancers ([#156](https://github.com/runpod/runpod-flash/issues/156)) ([334d582](https://github.com/runpod/runpod-flash/commit/334d5825592f514482c95c4b6f15a4f25ce03ba5))
* fix usage on VPNs because aiodns is flaky ([c55c97b](https://github.com/runpod/runpod-flash/commit/c55c97b0696aeb3632ce8623d1a1b8c9058831cf))

## [0.22.0](https://github.com/runpod/runpod-flash/compare/v0.21.0...v0.22.0) (2026-01-27)


### Features

* implement cross-endpoint routing reliability infrastructure ([#149](https://github.com/runpod/runpod-flash/issues/149)) ([cb6a226](https://github.com/runpod/runpod-flash/commit/cb6a2268836d449e4d3445ef787c5b7c184bbea6))
* implement upfront resource provisioning in deployment flow ([#152](https://github.com/runpod/runpod-flash/issues/152)) ([b9c5571](https://github.com/runpod/runpod-flash/commit/b9c5571db3e260b0456e62dd77329db6e754822b))

## [0.21.0](https://github.com/runpod/runpod-flash/compare/v0.20.1...v0.21.0) (2026-01-26)


### Features

* add "live-" prefix to live serverless endpoints ([#150](https://github.com/runpod/runpod-flash/issues/150)) ([5c8fa33](https://github.com/runpod/runpod-flash/commit/5c8fa33326eb6f4d1bff4cc8d8e09d7eb97821dc))

## [0.20.1](https://github.com/runpod/runpod-flash/compare/v0.20.0...v0.20.1) (2026-01-22)


### Performance Improvements

* **tests:** make parallel test execution the default ([#145](https://github.com/runpod/runpod-flash/issues/145)) ([3faf170](https://github.com/runpod/runpod-flash/commit/3faf1706fa7252c56c8fab68e7dc95b570845245))

## [0.20.0](https://github.com/runpod/runpod-flash/compare/v0.19.0...v0.20.0) (2026-01-15)


### Features

* add generic handler factory and build integration for Flash ([#130](https://github.com/runpod/runpod-flash/issues/130)) ([8c1e6b8](https://github.com/runpod/runpod-flash/commit/8c1e6b86022a0c5f91dcf1832adf467607004f01))
* add GET /manifest endpoint for mothership service discovery ([#139](https://github.com/runpod/runpod-flash/issues/139)) ([2956f09](https://github.com/runpod/runpod-flash/commit/2956f09318b459183b21a387c10d49bad03f19ee))
* AE-1741 manifest management via gql for flash client ([#144](https://github.com/runpod/runpod-flash/issues/144)) ([83979e7](https://github.com/runpod/runpod-flash/commit/83979e7a80e6789931f555cd882ca77398a43615))
* **build:** Add cross-platform build support and package exclusion ([#135](https://github.com/runpod/runpod-flash/issues/135)) ([68e0539](https://github.com/runpod/runpod-flash/commit/68e05391250a1232d4382baefedea81e45ca2f66))
* complete `[@remote](https://github.com/remote)` support for LoadBalancer endpoints ([#131](https://github.com/runpod/runpod-flash/issues/131)) ([f2f34c0](https://github.com/runpod/runpod-flash/commit/f2f34c07b0d02a7c42c51789cb25c2f5eaaacc41))
* cross-endpoint routing for serverless functions ([#129](https://github.com/runpod/runpod-flash/issues/129)) ([57ff437](https://github.com/runpod/runpod-flash/commit/57ff437f916ffbd0b29ec989a0361d6af674ca58))
* mothership manifest sync and caching ([#140](https://github.com/runpod/runpod-flash/issues/140)) ([20490ea](https://github.com/runpod/runpod-flash/commit/20490ea3a749e93a33daf41cc98cebbc30669b5b))
* **mothership:** implement auto-provisioning with manifest ([#136](https://github.com/runpod/runpod-flash/issues/136)) ([14effd4](https://github.com/runpod/runpod-flash/commit/14effd4ab5ed506206c36153dd9c72485deafa37))


### Bug Fixes

* **drift:** Exclude runtime fields from config hash to prevent false positives ([#132](https://github.com/runpod/runpod-flash/issues/132)) ([13ced50](https://github.com/runpod/runpod-flash/commit/13ced50558be287c235b272f3419babf168b6af1))


### Documentation

* **architecture:** Add deployment architecture specification ([#141](https://github.com/runpod/runpod-flash/issues/141)) ([b1de925](https://github.com/runpod/runpod-flash/commit/b1de9251a5c90dbfdfe7288a161f7bef51b4fa7f))

## [0.19.0](https://github.com/runpod/runpod-flash/compare/v0.18.0...v0.19.0) (2025-12-12)


### Features

* AE-1512: deploy() and undeploy() deployable resources directly ([#126](https://github.com/runpod/runpod-flash/issues/126)) ([3deac3a](https://github.com/runpod/runpod-flash/commit/3deac3a91b84fa4cf07cf553c46431907290a61c))
* **cli:** Add --auto-provision flag to flash run command ([#125](https://github.com/runpod/runpod-flash/issues/125)) ([ee5793c](https://github.com/runpod/runpod-flash/commit/ee5793c33537acc15e26b680e3bac5aedb3c0735))


### Code Refactoring

* use env vars FLASH_HOST and FLASH_PORT ([#128](https://github.com/runpod/runpod-flash/issues/128)) ([117a6ae](https://github.com/runpod/runpod-flash/commit/117a6aea91b9ca53fc3671150f746766307dbab4))

## [0.18.0](https://github.com/runpod/runpod-flash/compare/v0.17.1...v0.18.0) (2025-11-28)


### Features

* **cli:** Add `flash undeploy` command for endpoint management ([#121](https://github.com/runpod/runpod-flash/issues/121)) ([cd32ffc](https://github.com/runpod/runpod-flash/commit/cd32ffc40ac26c2f1aaa1235b044798ec7b9f605))


### Code Refactoring

* move endpoint deletion logic to proper abstraction layers ([#124](https://github.com/runpod/runpod-flash/issues/124)) ([c253d3b](https://github.com/runpod/runpod-flash/commit/c253d3b6f959dc8514b91b5e79f6f73fe9593b89))

## [0.17.1](https://github.com/runpod/runpod-flash/compare/v0.17.0...v0.17.1) (2025-11-19)


### Documentation

* update readme for alpha release ([#120](https://github.com/runpod/runpod-flash/issues/120)) ([e8093d8](https://github.com/runpod/runpod-flash/commit/e8093d8ac878c13e578dc0ded823dfe8c73120f3))

## [0.17.0](https://github.com/runpod/runpod-flash/compare/v0.16.1...v0.17.0) (2025-11-19)


### Features

* add user-friendly error messages for missing RUNPOD_API_KEY ([#117](https://github.com/runpod/runpod-flash/issues/117)) ([32dc093](https://github.com/runpod/runpod-flash/commit/32dc0937dda02a8b6178f3f5b2219f18de1f933e))


### Documentation

* improved flash init skeleton, contributing, and misc cleanup ([#118](https://github.com/runpod/runpod-flash/issues/118)) ([91acf1a](https://github.com/runpod/runpod-flash/commit/91acf1a87b5cdcf7f66c2bfa976f6132a8ca3cea))

## [0.16.1](https://github.com/runpod/runpod-flash/compare/v0.16.0...v0.16.1) (2025-11-14)


### Bug Fixes

* **skeleton:** Fix flash init missing hidden files in wheel distributions ([#115](https://github.com/runpod/runpod-flash/issues/115)) ([c3bf137](https://github.com/runpod/runpod-flash/commit/c3bf1376382cad8dcfb5c33d33e8876b97585384))

## [0.16.0](https://github.com/runpod/runpod-flash/compare/v0.15.0...v0.16.0) (2025-11-14)


### Features

* **cli:** Add flash init with project skeleton template and in-place initialization ([#110](https://github.com/runpod/runpod-flash/issues/110)) ([155d6ee](https://github.com/runpod/runpod-flash/commit/155d6ee64014936c082173751d0978c7cba39092))

## [0.15.0](https://github.com/runpod/runpod-flash/compare/v0.14.0...v0.15.0) (2025-11-14)


### Features

* **client:** add async function support to remote decorator ([#112](https://github.com/runpod/runpod-flash/issues/112)) ([b0222e0](https://github.com/runpod/runpod-flash/commit/b0222e006ca9b3e7cd8ea0b55804dcabf6d8fce8))
* **resources:** Support for Serverless.type QB|LB ([#109](https://github.com/runpod/runpod-flash/issues/109)) ([6e63459](https://github.com/runpod/runpod-flash/commit/6e63459d1a174836912c7b72590341ea6b3cf2b6))

## [0.14.0](https://github.com/runpod/runpod-flash/compare/v0.13.0...v0.14.0) (2025-10-31)


### Features

* AE-1202 add flash cli cmd init and run ([#96](https://github.com/runpod/runpod-flash/issues/96)) ([75b2baf](https://github.com/runpod/runpod-flash/commit/75b2baf4a35c9e6f3fc973ed287bd8da9285c607))

## [0.13.0](https://github.com/runpod/runpod-flash/compare/v0.12.0...v0.13.0) (2025-10-09)


### Features

* Command Line Interface ([#50](https://github.com/runpod/runpod-flash/issues/50)) ([5f4cde6](https://github.com/runpod/runpod-flash/commit/5f4cde6b0a8a7e082a0a1e0ce184d677309f0cfd))


### Bug Fixes

* repair build and release actions ([#97](https://github.com/runpod/runpod-flash/issues/97)) ([4a73fa8](https://github.com/runpod/runpod-flash/commit/4a73fa811729b612f9367e4b2c16831b553e00eb))


### Code Refactoring

* deprecate hf_models_to_cache ([#95](https://github.com/runpod/runpod-flash/issues/95)) ([963bfd7](https://github.com/runpod/runpod-flash/commit/963bfd7ee25f204b85888f09e444b1ecf0b75ffb))

## [0.12.0](https://github.com/runpod/runpod-flash/compare/v0.11.0...v0.12.0) (2025-09-15)


### Features

* better clarity on provisioning CPU Serverless Endpoints ([#88](https://github.com/runpod/runpod-flash/issues/88)) ([efec224](https://github.com/runpod/runpod-flash/commit/efec224029e8c03133f8f4840b38308f141743ce))
* thread-safe resource provisions and remote executions ([#91](https://github.com/runpod/runpod-flash/issues/91)) ([440b36f](https://github.com/runpod/runpod-flash/commit/440b36f6e15bffc68f1f77589d7b8fa4d6fc2025))


### Bug Fixes

* download accelerator changes broken regular endpoint invocations ([#86](https://github.com/runpod/runpod-flash/issues/86)) ([759f996](https://github.com/runpod/runpod-flash/commit/759f996208ebb5f052cda5e8b52b8c3b7a542b26))

## [0.11.0](https://github.com/runpod/runpod-flash/compare/v0.10.0...v0.11.0) (2025-08-19)


### Features

* Add download acceleration for dependencies and HuggingFace models ([#83](https://github.com/runpod/runpod-flash/issues/83)) ([e47c9e3](https://github.com/runpod/runpod-flash/commit/e47c9e37030ead1831893dd70a1322421befbaad))

## [0.10.0](https://github.com/runpod/runpod-flash/compare/v0.9.0...v0.10.0) (2025-08-07)


### Features

* Add idempotent network volume deployment ([#79](https://github.com/runpod/runpod-flash/issues/79)) ([289d333](https://github.com/runpod/runpod-flash/commit/289d333aaaf48e00bfdad2a5f6356bdfc6bcf286))

## [0.9.0](https://github.com/runpod/runpod-flash/compare/v0.8.0...v0.9.0) (2025-08-04)


### Features

* AE-961 Add class serialization caching for remote execution ([#76](https://github.com/runpod/runpod-flash/issues/76)) ([95f9eed](https://github.com/runpod/runpod-flash/commit/95f9eed1810e6a623091348c326e2ea571c6dddf))

## [0.8.0](https://github.com/runpod/runpod-flash/compare/v0.7.0...v0.8.0) (2025-07-22)


### Features

* AE-815 Add class based execution ([#72](https://github.com/runpod/runpod-flash/issues/72)) ([d2a70ad](https://github.com/runpod/runpod-flash/commit/d2a70ad702bfd7e8f9c137eb2ce8263d1dfbd667))

## [0.7.0](https://github.com/runpod/runpod-flash/compare/0.6.0...v0.7.0) (2025-07-21)


### Features

* AE-892 - Lock the network volume region ([#67](https://github.com/runpod/runpod-flash/issues/67)) ([2b7a3ea](https://github.com/runpod/runpod-flash/commit/2b7a3eae2b1f4b343b20a1548e63507e88b1adbc))


### Bug Fixes

* downgrade release-please to v3 for simplicity ([#70](https://github.com/runpod/runpod-flash/issues/70)) ([06f05d1](https://github.com/runpod/runpod-flash/commit/06f05d1bb0e7fca9208a86248432e9d72a20036a))
* use default release-please PR title pattern ([#68](https://github.com/runpod/runpod-flash/issues/68)) ([786df98](https://github.com/runpod/runpod-flash/commit/786df986d2f36d324bd470937aa9dae7c0cc38be))

## [0.6.0](https://github.com/runpod/runpod-flash/compare/0.5.5...0.6.0) (2025-07-10)


### Features

* AE-811 Add a class to create network volume using REST ([abb82b7](https://github.com/runpod/runpod-flash/commit/abb82b74bf232833d96baee56d2b352202223b6e))

## [0.5.5](https://github.com/runpod/runpod-flash/compare/0.5.4...0.5.5) (2025-07-10)


### Bug Fixes

* remove sigstore signing to simplify PyPI publishing ([65037c5](https://github.com/runpod/runpod-flash/commit/65037c5f4c11bb8a08292b98f17d1f005784e5ed))

## [0.5.4](https://github.com/runpod/runpod-flash/compare/0.5.3...0.5.4) (2025-07-10)


### Bug Fixes

* revert to simple working CI/release workflows, remove broken shared workflow ([3fe4cf0](https://github.com/runpod/runpod-flash/commit/3fe4cf02472e6cc19cd46a8104b248e2e7367be3))
* separate sigstore artifacts from dist/ to avoid PyPI validation errors ([6b0038e](https://github.com/runpod/runpod-flash/commit/6b0038ea1c1df058263d2395248fb96d4c88cdeb))


### Documentation

* add contributing section to README with release system documentation reference ([8b87b9c](https://github.com/runpod/runpod-flash/commit/8b87b9cb09262f5be74a8f18435d685b0360d1c5))

## [0.5.3](https://github.com/runpod/runpod-flash/compare/0.5.2...0.5.3) (2025-07-10)


### Bug Fixes

* update sigstore action to v3.0.0 to avoid deprecated upload-artifact@v3 ([92a6891](https://github.com/runpod/runpod-flash/commit/92a6891e26d327b2c99926373822e0eede08eebb))

## [0.5.2](https://github.com/runpod/runpod-flash/compare/0.5.1...0.5.2) (2025-07-10)


### Bug Fixes

* revert to simple working CI/release workflows, remove broken shared workflow ([62dab19](https://github.com/runpod/runpod-flash/commit/62dab1937be0d6c918261299e3be197cda0f44a9))

## [0.5.1](https://github.com/runpod/runpod-flash/compare/0.5.0...0.5.1) (2025-07-10)


### Bug Fixes

* adjust release-please title pattern to match existing PR [#55](https://github.com/runpod/runpod-flash/issues/55) ([091dbff](https://github.com/runpod/runpod-flash/commit/091dbffe8b26142eeedc07e1855d132e948cc3cd))
* only upload artifacts to release when tag_name is available ([e8bdcf1](https://github.com/runpod/runpod-flash/commit/e8bdcf12cf7aeb57c04232aea2f14174c743481b))
* revert to clean release-please title pattern for future releases ([c0171ca](https://github.com/runpod/runpod-flash/commit/c0171cab08f0ea62a861c1a0b8012e1c4dbd89c7))
* still seeing issues with the CI and Release ([#60](https://github.com/runpod/runpod-flash/issues/60)) ([81df31a](https://github.com/runpod/runpod-flash/commit/81df31a0853c6436964afeb2511499396c66fe0d))

## [0.5.0](https://github.com/runpod/runpod-flash/compare/v0.4.2...0.5.0) (2025-07-09)


### Features

* pytest with unit and integration ([19dcac9](https://github.com/runpod/runpod-flash/commit/19dcac908ddd5f2cdac7d9365c3b2066fbe04fdd))


### Bug Fixes

* cannot do both ([c64d895](https://github.com/runpod/runpod-flash/commit/c64d89550f871b5fb685adc6dcb913cbd61217e4))
* configure release-please to handle all commit types ([#57](https://github.com/runpod/runpod-flash/issues/57)) ([7de5c8d](https://github.com/runpod/runpod-flash/commit/7de5c8d146eaf2fddde07bc9c5ecf260e37029e3))
* correction ([9982236](https://github.com/runpod/runpod-flash/commit/99822362fd99698a30ddcaab6bbd5513ed5549d8))
* Pydantic's deprecation warning of class Config ([d1f18f2](https://github.com/runpod/runpod-flash/commit/d1f18f207568866aadb487ca99747b542174142b))
* ruff cleanup ([8251597](https://github.com/runpod/runpod-flash/commit/825159748fdb8755aeee03d1740081915fd0882f))
* ruff linting ([6d8e87c](https://github.com/runpod/runpod-flash/commit/6d8e87cb095b8d38977c5b3bfe981c8ebe580c93))


### Documentation

* pull request template ([#58](https://github.com/runpod/runpod-flash/issues/58)) ([0377fa4](https://github.com/runpod/runpod-flash/commit/0377fa4dfc439e56df30227a03cf77bb80dfa28a))

## [0.4.2](https://github.com/runpod/runpod-flash/compare/v0.4.1...v0.4.2) (2025-06-26)


### Bug Fixes

* consolidate PodTemplate overrides with the defaults per ServerlessResource ([2b8dc16](https://github.com/runpod/runpod-flash/commit/2b8dc165c46ce5d70651f7060075815977034557))
* template overrides ([0fd6429](https://github.com/runpod/runpod-flash/commit/0fd6429ee1ad5ade9df5bfc4bbbdc9f29683b75b))

## [0.4.1](https://github.com/runpod/runpod-flash/compare/v0.4.0...v0.4.1) (2025-06-26)


### Bug Fixes

* uv publish ([6c4f9a9](https://github.com/runpod/runpod-flash/commit/6c4f9a9d4deeffc4733798208e771cd136ab2e80))
* uv publish ([55ae7c0](https://github.com/runpod/runpod-flash/commit/55ae7c08d70e079bb0abe2938b0d13771de3dce1))

## [0.4.0](https://github.com/runpod/runpod-flash/compare/v0.3.0...v0.4.0) (2025-06-26)


### Features

* CPU Endpoints and Live Serverless ([c335fd1](https://github.com/runpod/runpod-flash/commit/c335fd11cbc65c4a18edabe007982506bee5e6c3))


### Bug Fixes

* CpuInstanceType values ([9cf958b](https://github.com/runpod/runpod-flash/commit/9cf958b381d56b4aa5d42c0393500818d6de3c34))

## [0.3.0](https://github.com/runpod/runpod-flash/compare/v0.2.1...v0.3.0) (2025-06-23)


### Features

* added diffusers as examples group dependency ([e330bf9](https://github.com/runpod/runpod-flash/commit/e330bf9ed2305470543dd39470c1803959479821))
* AE-392: serverless execute function calls runpod SDK ([43900e5](https://github.com/runpod/runpod-flash/commit/43900e59e3c4e08b5a903751ce5525fcfee93f13))
* AE-394: examples updated ([27c3afb](https://github.com/runpod/runpod-flash/commit/27c3afbb93667d7a800af0f3e49361cb5b806070))
* AE-394: examples updated ([d2bfe1b](https://github.com/runpod/runpod-flash/commit/d2bfe1b8c8682655a62148fcc3d0f0041a2f35d4))
* AE-394: LiveServerless that locks the template id ([d1032a6](https://github.com/runpod/runpod-flash/commit/d1032a6b2788a18eb19eee991134fb8152733a11))
* AE-394: LiveServerless that locks the template id ([1ba5bfc](https://github.com/runpod/runpod-flash/commit/1ba5bfce5d597a040ad66358dad2a86b0a66c3d6))
* AE-394: resilient serverless calls with retries and auto-cancellations ([78bb250](https://github.com/runpod/runpod-flash/commit/78bb2505b7f7e02c82a2fe54ca1643de73affb54))
* AE-394: retry, backoff, on cancel appropriately ([4b75941](https://github.com/runpod/runpod-flash/commit/4b759419f322f1dac87b4fd65d19430928ff9144))
* AE-394: retry, backoff, on cancel appropriately ([96d1001](https://github.com/runpod/runpod-flash/commit/96d1001915654d3f101ac32bde972f17a0a3ff22))
* AE-432: Logging ([a93f88e](https://github.com/runpod/runpod-flash/commit/a93f88e20a2fb0f6d741aebe98db85cc8b3ed88b))
* AE-432: Logging ([718de18](https://github.com/runpod/runpod-flash/commit/718de18289b2d605ecc01359c6be9b6290373d3a))
* AE-442: Docker image template polish + cleanup ([75471b2](https://github.com/runpod/runpod-flash/commit/75471b2cbb40d31d0d82d4562072d8c16a59cb8e))
* AE-470: shadow deploy as runpod_flash ([749d427](https://github.com/runpod/runpod-flash/commit/749d427b9095d77742ddde679d1fc44d999d5d30))
* AE-494: remove all docker- worker-related content ([72a4b9a](https://github.com/runpod/runpod-flash/commit/72a4b9a74761affdb1b0e9381bcaf49763829bac))
* AE-494: removed any worker-related content ([72464d1](https://github.com/runpod/runpod-flash/commit/72464d1881584a2003d2edbd2cf9e6a982455592))
* AE-517: logs from remote printed as `Remote | <log>` ([d8f4ee1](https://github.com/runpod/runpod-flash/commit/d8f4ee1323696b3f9cd8e5c2e928eb8538c6d2cd))
* AE-517: logs from remote printed as `Remote | <log>` ([ab1d729](https://github.com/runpod/runpod-flash/commit/ab1d72900e21cccebd5448f63220295f113aeeb1))
* AE-517: remote error logs are piped back ([b668e3e](https://github.com/runpod/runpod-flash/commit/b668e3ef0d97babebfaf35f31d053be8fbee7ad9))
* AE-517: remote error logs are piped back ([4c5bf4c](https://github.com/runpod/runpod-flash/commit/4c5bf4c03d85a55a10739ea0911cff7d257ffe1b))
* AE-565 singledispatch stub_resource for LiveServerless ([5fe2de7](https://github.com/runpod/runpod-flash/commit/5fe2de7cf74fc39ced6699aeb6cf4f48af21f3e9))
* incremental changes, starting with deployments ([1ce1b3b](https://github.com/runpod/runpod-flash/commit/1ce1b3b04c2fdff2bfb870c6b9065bd6213a506d))
* is_deployed() to check and redeploy in case endpoint is inaccessible ([4aa0932](https://github.com/runpod/runpod-flash/commit/4aa0932c9f99b08a0d234d4d843dd6339cbc7dd1))
* Prefer A40 for GPU list when "any" is set ([6a60418](https://github.com/runpod/runpod-flash/commit/6a60418452a39501b3142096e9ab8afa01628953))
* preparing json.dump of complex objects with normalize_for_json ([48cedd6](https://github.com/runpod/runpod-flash/commit/48cedd64e9140d261f2b3327a3611715d2bf3e38))
* Pydantic modeling of Runpod resources ([87067bb](https://github.com/runpod/runpod-flash/commit/87067bbae31d7de618d0edd1d78289fef1c0f6d1))
* remote stub for ServerlessEndpoint calls ([739aa93](https://github.com/runpod/runpod-flash/commit/739aa93775e296fbb99aa9afccc07b12ae60ea50))
* resilient redeployments ([fd2e78d](https://github.com/runpod/runpod-flash/commit/fd2e78d42531f83cc3b66d197fb2195244d65336))
* resilient serverless calls with retries and auto-cancellations when unhealthy/throttled ([9f53e8c](https://github.com/runpod/runpod-flash/commit/9f53e8cb36871ff58b491cd8bf1851bf3d1029cc))
* resource utility, `inquire` to map runpod calls to pydantic models ([096239f](https://github.com/runpod/runpod-flash/commit/096239fae42dbcfafb141b48f294942e0e840990))
* ServerlessEndpoint inherits ServerlessResource ([c0e64f9](https://github.com/runpod/runpod-flash/commit/c0e64f930bf38f2a956463d74f6bccfafee13353))
* ServerlessResource.run_sync ([33e3fff](https://github.com/runpod/runpod-flash/commit/33e3fffeb121977c14614f0f0d57cfb232756e8c))
* SingletonMixin for ResourceManager and RemoteExecutionClient ([e0ae91b](https://github.com/runpod/runpod-flash/commit/e0ae91b0627226873b131abdb26ab6d86e88e4d2))
* Support for ServerlessEndpoint remote calls ([e53f3aa](https://github.com/runpod/runpod-flash/commit/e53f3aa4ef44f6e8a87d2d37fe7ae9b5f10e29f6))


### Bug Fixes

* add missing arg to request ([21d4e0c](https://github.com/runpod/runpod-flash/commit/21d4e0ceb6e255a5d5df1440c8fcbe95a75f802c))
* add missing arg to request ([656150f](https://github.com/runpod/runpod-flash/commit/656150fc082b7b519d4b6c940258af8ac0b62e04))
* AE-392: deployable serverless corrections ([57b1cd2](https://github.com/runpod/runpod-flash/commit/57b1cd21fa63bd9d11447cdba9a865ca1a3aeb8b))
* AE-392: deployable serverless corrections ([74bd17d](https://github.com/runpod/runpod-flash/commit/74bd17d0dbf7bd24ddf3de3734405615a12af1a8))
* cleanup from ruff suggestions ([61048d2](https://github.com/runpod/runpod-flash/commit/61048d2d7922ad53289fa078f9e48ac8b60dada7))
* cleanup project setup ([9ed50ab](https://github.com/runpod/runpod-flash/commit/9ed50ab925e465ffeb8cedbffbb44036bdfb35c8))
* cleanup unused code ([ad78de7](https://github.com/runpod/runpod-flash/commit/ad78de7942587dbb0100a3101a5185ebc1c0cc52))
* implicit load_dotenv() before everything ([ff0030b](https://github.com/runpod/runpod-flash/commit/ff0030bd7c033d4a8e6b9849c76075bccb99beaa))
* implicit load_dotenv() before everything ([2d3c710](https://github.com/runpod/runpod-flash/commit/2d3c71015a944515fa667aaa662692f14596b5e0))
* make examples ([7de342c](https://github.com/runpod/runpod-flash/commit/7de342cafab59bffe764833d5a1f02b7ff691654))
* missed these commits ([5ed3a8a](https://github.com/runpod/runpod-flash/commit/5ed3a8a4bc6065eb1c4313595f325581666d33ae))
* passing GPU names aren't supported yet ([3798ac0](https://github.com/runpod/runpod-flash/commit/3798ac06ce1de21b711f5a7236ebaa884ffc22ae))
* Put A40s in front of the list when gpus=any ([717efb1](https://github.com/runpod/runpod-flash/commit/717efb168059826ce2857c3be3d476a43e0eddfb))
* python 3.9 compatible ([5ddfd09](https://github.com/runpod/runpod-flash/commit/5ddfd09d2fba9403aec9940eec479db5f259c1d8))
* release-please bugs ([fd6d02e](https://github.com/runpod/runpod-flash/commit/fd6d02eb2a625082e2f31394577debc5c066b0f4))
* release-please bugs ([76b3eee](https://github.com/runpod/runpod-flash/commit/76b3eee81d5a7e9a4eca1b06b0cdc6256d4d9743))
* ruff cleanup ([739adaf](https://github.com/runpod/runpod-flash/commit/739adaff98f816dfb95f6b46887ba80b6e8e2aaa))
* simplify `make dev` that syncs and installs examples ([d1a3e62](https://github.com/runpod/runpod-flash/commit/d1a3e62174b066330591a96cc98d7b7e1238f221))
* try catch for matrix example ([f7a5012](https://github.com/runpod/runpod-flash/commit/f7a5012a1f177e96e3565ec86638e2712846bb71))
* use of pathlib.Path where appropriate ([4ee717c](https://github.com/runpod/runpod-flash/commit/4ee717ca853ce88598c60db0cc3770b1f689d0ce))

## [0.2.1](https://github.com/runpod/runpod-flash/compare/0.2.0...v0.2.1) (2025-06-23)


### Bug Fixes

* implicit load_dotenv() before everything ([2d3c710](https://github.com/runpod/runpod-flash/commit/2d3c71015a944515fa667aaa662692f14596b5e0))
