"""Registry channel package.

Registry is one channel with both ingress and egress. The browser UI is a
client of registry HTTP ingress, not a separate workflow path.

This package will own:

- ingress translation from registry-native requests into workflow calls
- egress publication of registry-native outcomes/timeline updates
- HTTP route registration and validation
- UI shell/static serving
- registry-specific presenters

During Milestone 1 this package is structural only.
"""
