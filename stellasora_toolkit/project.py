"""Distribution identity shared by launchers, update checks and release tooling."""

GITHUB_REPOSITORY = 'beichen24a1/StellaSoraTracker'
GITEE_REPOSITORY = 'beichen_24/StellaSoraTracker'
UPDATE_MANIFESTS = {
    'beta': f'https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/app_update_beta.json',
    'stable': f'https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/app_update_github.json',
    'gitee': f'https://gitee.com/{GITEE_REPOSITORY}/raw/main/app_update_gitee.json',
}
UPDATE_MANIFEST_URL = UPDATE_MANIFESTS['beta']
