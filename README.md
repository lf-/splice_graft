# splice graft 🌿

This tool helps you change the default branch on a bunch of Git repos.

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

