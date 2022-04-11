# splice graft 🌿

This is a tool to do various operations on the GitHub API.

## Usage

### Installation

You can install for usage with `pip install --user https://github.com/lf-/splice_graft/archive/refs/heads/main.zip`

or for development with `pip install --user -e .` in a clone of the repository.

### Supported operations

```
» python splice_graft.py --help
usage: splice_graft.py [-h] {list,fix,find_pr,set} ...

positional arguments:
  {list,fix,find_pr,set}
    list                List non-archived repositories with the `master` default branch
    fix                 Rename the default branch for a (stdin) list of repos
    find_pr             Finds a pull request touching the specified files
    set                 Sets some attributes on a set of repositories (from stdin)

options:
  -h, --help            show this help message and exit
```

### Finding a PR touching some file

```
# find any open PR touching both filename1 and filename2
» splice-graft find_pr owner/repo filename1 filename2

# find a closed or merged PR touching filename1
» splice-graft find_pr -s closed -s merged owner/repo filename1

# find a closed or merged PR touching anything under blah/
» splice-graft find_pr -s closed -s merged -m re gankra/gankra.github.io '^blah/.*'

# find a PR of any status touching anything under blah/
» splice-graft find_pr -s any -m re gankra/gankra.github.io '^blah/.*'
```

### Renaming branches

This tool helps you change the default branch on a bunch of GitHub repos to
`main` or another name. It creates a new branch using the GitHub API and sets
the default branch to it. This tool does not change your client side git
configs and branches, which need to be updated with `git branch -m main` and
`git branch -u origin/main` on your clones.

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

