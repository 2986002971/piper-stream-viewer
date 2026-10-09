# Third-party notices

MIT applies to project-authored code only. No upstream robot/camera CAD, USD or private client configuration is bundled.

| Dependency | License / distribution |
|---|---|
| NVIDIA Omniverse WebRTC streaming library 5.6.0 | NVIDIA SDK license, copied verbatim to `third_party/NVIDIA-STREAMING-SDK-LICENSE.txt`. This SDK is compiled into the client bundle; NVIDIA terms remain applicable. |
| deepcopy 2.1.0 | MIT; SDK runtime dependency. Notice copied to `third_party/DEEPCOPY-LICENSE.txt`. |
| TypeScript 5.8.3 | Apache-2.0, build-time dependency installed through lockfile, not shipped in built client. |
| Vite 6.3.5 | MIT, build-time dependency installed through lockfile, not shipped in built client. |

Other transitive build dependencies retain their installed package licenses. Source checkout does not vendor node_modules.
`package_client.py` includes third_party notices in every built package. SDK licensing is not replaced by the project's MIT license.
