# Testing and releases

`main` contains changes being tested. Published GitHub releases are the stable
versions offered to users by HACS. Merging to `main` does not publish a release
once the repository has its first published release.

## Establish the first stable release

Before merging changes that require a newer Home Assistant version, publish a
baseline release from the last working commit on `main`. Its tag should match the
integration version in `custom_components/thermoworks_cloud/manifest.json` (for
example, tag `v0.1.0` for manifest version `0.1.0`). Target that exact commit,
including its original `hacs.json`, rather than a later commit containing a new
minimum Home Assistant version.

Create a GitHub release for the tag and mark it as the latest stable release.
A tag alone does not establish a HACS release. Keep this release available for
users who cannot yet upgrade Home Assistant.

Before the first release exists, HACS distributes the default branch. Existing
users should refresh repository information and select the stable release once
it is published.

## Test changes from main

1. Merge the changes into `main` and check the Tests, HACS, and hassfest workflows.
2. On your test Home Assistant installation, open this integration in HACS.
   Refresh its repository information, then use **Redownload** and select `main`.
3. Restart Home Assistant to load the downloaded code.
4. Check integration setup, entity values, gateway/fan relationships, and logs.

Keep `hide_default_branch` absent or false in `hacs.json` so `main` remains
available in the download selector. Explicitly select `main` each time you deploy
test code: do not assume an ordinary update notification or install action will
continue selecting that branch after releases exist.

The `update.install` action can also request the branch explicitly:

```yaml
action: update.install
target:
  entity_id: update.REPLACE_WITH_YOUR_INTEGRATION_UPDATE_ENTITY
data:
  version: main
```

Replace the placeholder with the HACS update entity for ThermoWorks Cloud.
Restart Home Assistant after the download. Return to a stable version by
redownloading its release in HACS and restarting again.

## Publish tested code

1. Choose the next integration version and update `version` in
   `custom_components/thermoworks_cloud/manifest.json`. This is separate from the
   Home Assistant version pinned in `requirements.txt`.
2. Confirm `hacs.json` declares the oldest supported Home Assistant version and
   that the README agrees. Test that version and the development pin when raising
   the minimum.
3. Merge the version change, wait for CI, and test that exact commit in Home
   Assistant. Record its commit SHA.
4. In GitHub's Releases page, create a release with a matching tag (for example,
   `v0.2.0` for manifest version `0.2.0`) targeting the tested commit SHA. Use a
   draft while preparing notes. Do not let subsequent merges change which commit
   you release.
5. Lead the notes with any new minimum Home Assistant version, describe the fixes,
   and identify the last release supporting older installations.
6. Publish as a stable release and mark it as latest. Verify HACS offers it on a
   release-based installation.

No ZIP upload is needed for the current repository layout. Do not enable
`zip_release` unless release assets are introduced. For optional beta testing,
publish a GitHub prerelease; normal users should keep prereleases disabled.

## References

- [HACS integration releases](https://www.hacs.dev/docs/publish/integration/)
- [HACS repository settings](https://hacs.dev/docs/publish/start/)
- [HACS update actions](https://www.hacs.dev/docs/use/entities/update/)
