#!/usr/bin/env python3
import argparse
import os
import sys
from typing import Any

import requests


API_BASE = 'https://api.github.com'
API_ENDPOINT = API_BASE + '/graphql'
REPLACING_BRANCH = 'master'


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def get_auth_token():
    apikey = os.environ.get('GH_ACCESS_TOKEN')
    if not apikey:
        raise EnvironmentError('Token missing. Please put your API token in '
                'the GH_ACCESS_TOKEN environment variable')
    return apikey


def get_auth_header():
    return 'token ' + get_auth_token()


"""
Gets an element by dot separated path in a nested dict-like object.
"""
def find(path, json):
    keys = path.split('.')
    ret = json
    for key in keys:
        elem = ret.get(key)
        if elem is None:
            # eprint('None in', ret, key)
            # eprint('CONTEXT', path, json)
            return None
        ret = elem
    return ret


def get_repos(user, curs=None, any_branch=False):
    QUERY = """
    query ($who: String!, $curs: String = null) {
      user(login: $who) {
        repositories(affiliations: OWNER, isFork: false, first: 100, after: $curs) {
          nodes {
            nameWithOwner
            isArchived
            defaultBranchRef {
              name
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """
    VARIABLES = {
        'who': user,
        'curs': curs,
    }
    res = graphql_query(QUERY, VARIABLES)
    has_next = find('data.user.repositories.pageInfo.hasNextPage', res)
    next_curs = find('data.user.repositories.pageInfo.endCursor', res) if has_next else None
    repos = find('data.user.repositories.nodes', res)
    assert repos
    # filter just repos that aren't fixed yet
    repos = [repo['nameWithOwner'] for repo in repos if (any_branch or find('defaultBranchRef.name', repo) == REPLACING_BRANCH) and not repo['isArchived']]
    return (repos, next_curs)


def get_user():
    QUERY = """
    {
      viewer {
        login
      }
    }
    """
    return find('data.viewer.login', graphql_query(QUERY))


def graphql_query(query, variables={}):
    api_headers = {
        'Authorization': get_auth_header(),
    }
    body = {
        'query': query,
        'variables': variables,
    }
    return requests.post(API_ENDPOINT, json=body, headers=api_headers).json()


def cli_list(args):
    user = args.user
    if not user:
        user = get_user()

    curs = None
    done = False
    while not done:
        (repos, curs) = get_repos(user, curs=curs, any_branch=args.all)
        for repo in repos:
            print(repo)
        if curs is None:
            done = True


"""
Returns (repoID, branchTipOID) for a given repo and branch. The given `branch`
does not need to be fully qualified.
"""
def get_branch_info(repo, branch):
    owner, _, name = repo.partition('/')
    QUERY = """
    query ($owner: String!, $repoName: String!, $branch: String!) {
      repository(owner: $owner, name: $repoName) {
        id
        ref(qualifiedName: $branch) {
          target {
            oid
          }
        }
      }
    }
    """
    VARIABLES = {
        'owner': owner,
        'repoName': name,
        'branch': branch,
    }
    res = graphql_query(QUERY, VARIABLES)
    return (find('data.repository.id', res), find('data.repository.ref.target.oid', res))


"""
Creates a new git ref.

Parameters:
* repo_id -- the opaque id for the repo, from `get_branch_info()`
* branch  -- fully qualified branch name i.e. refs/heads/...
* tip_oid -- the git object ID of the tip of the new branch
"""
def new_ref(repo_id, branch, tip_oid):
    QUERY = """
    mutation ($repoId: ID!, $branch: String!, $newSha: GitObjectID!) {
      createRef(input: {repositoryId: $repoId, name: $branch, oid: $newSha}) {
        ref {
          name
          target {
            oid
          }
        }
      }
    }
    """
    VARIABLES = {
        'repoId': repo_id,
        'branch': branch,
        'newSha': tip_oid,
    }
    return graphql_query(QUERY, VARIABLES)


"""
Sets the default branch of `repo_path` to `branch`. GitHub does wacky stuff if
you give it a canonical branch name.
"""
def set_default_branch(repo_path: str, branch: str) -> requests.Response:
    BODY = {
        'default_branch': branch,
    }
    return patch_repo(repo_path, BODY)


def patch_repo(repo_path: str, body: dict[str, Any]) -> requests.Response:
    HEADERS = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': get_auth_header(),
    }
    # it's not supported in the v4 api :((((
    return requests.patch('{}/repos/{}'.format(API_BASE, repo_path), json=body, headers=HEADERS)


def cli_fix(args):
    new_branch_name = args.new_branch
    new_branch = 'refs/heads/{}'.format(args.new_branch)

    for line in sys.stdin:
        repo_path = line.rstrip()
        eprint('Processing', repo_path)

        # get the remote branch pointer of the branch we're fixing
        repo_id, branch_tip = get_branch_info(repo_path, REPLACING_BRANCH)
        eprint('>>', repo_path, REPLACING_BRANCH, 'is', branch_tip)

        resp = new_ref(repo_id, new_branch, branch_tip)
        errs = resp.get('errors')
        if errs:
            for err in errs:
                eprint('Error making a new branch in {}: {}'.format(repo_path, err['message']))

        resp = set_default_branch(repo_path, new_branch_name)
        if resp.status_code != 200:
            eprint('Got error updating default branch in {}: {}'.format(repo_path, resp.json()))
        eprint('Done', repo_path)


def cli_set(args: argparse.Namespace):
    body = {k: v for k, v in args.__dict__.items() if k != 'cmd' and v is not None}
    for line in sys.stdin:
        repo_path = line.rstrip()
        eprint('PATCH repo ', repo_path, 'with', body)
        patch_repo(repo_path, body)


def parse_bool(s: str) -> bool:
    s = s.lower()
    if s in {'y', 'yes', 'true', 'on'}:
        return True
    elif s in {'n', 'no', 'false', 'off'}:
        return False
    raise ValueError(f'Could not parse {s!r} as boolean, try yes/y/true/on or no/n/false/off')


def main():
    ap = argparse.ArgumentParser()
    sps = ap.add_subparsers()

    def fail(*args):
        ap.print_help()
        sys.exit(1)
    ap.set_defaults(cmd=fail)

    list_parser = sps.add_parser('list')
    list_parser.add_argument('user', help='User to find repos of', nargs='?', default=None)
    list_parser.add_argument('--all', '-a', help='List repos with any default branch', action='store_true', default=False)
    list_parser.set_defaults(cmd=cli_list)

    fix_parser = sps.add_parser('fix')
    fix_parser.add_argument('new_branch', help='New branch name', nargs='?', default='main')
    fix_parser.set_defaults(cmd=cli_fix)

    set_parser = sps.add_parser('set')
    set_parser.add_argument('--allow-squash-merge', help='Permit squash '
        'merge on this repo', default=None, type=parse_bool)
    set_parser.add_argument('--allow-rebase-merge', help='Permit rebase '
        'merge on this repo', default=None, type=parse_bool)
    set_parser.add_argument('--allow-merge-commit', help='Permit merge '
        'commits on this repo', default=None, type=parse_bool)
    set_parser.set_defaults(cmd=cli_set)

    args = ap.parse_args()
    args.cmd(args)


if __name__ == '__main__':
    main()
