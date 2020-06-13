# splice graft 🌿

This tool helps you change the default branch on a bunch of GitHub repos to
`main` or another name. It creates a new branch using the GitHub API and sets
the default branch to it. This tool does not change your client side git
configs and branches, which need to be updated with `git branch -m main` and
`git branch -u origin/main` on your clones.

## Usage

This program requires `requests`. It can be installed from pip, your distro package manager, or in a virtualenv.

```bash
$ # Grab an access token with scope 'repos' for your GitHub user account at https://github.com/settings/tokens
$ export GH_ACCESS_TOKEN='abcdef'
$ ./splice_graft.py list > repos.txt
$ # Now, go through the repository list and remove any that you don't want to use
$ ./splice_graft.py fix < repos.txt
```

## Project information

This project is licensed under the MIT License. Everyone is expected to follow
the Contributor Covenant code of conduct while participating in this project.

