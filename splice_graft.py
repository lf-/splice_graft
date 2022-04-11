#!/usr/bin/env python3
import abc
import textwrap
import argparse
import os
import sys
import dataclasses
import re
from typing import Any, Callable, Generator, Generic, Literal, Optional, TypeVar
import logging

import requests

API_BASE = 'https://api.github.com'
API_ENDPOINT = API_BASE + '/graphql'
REPLACING_BRANCH = 'master'
LOG_LEVEL = 'INFO'


class Colour:
    NORM = '\x1b[0m'
    BOLD = '\x1b[1m'

    @staticmethod
    def bold(s):
        return f'{Colour.BOLD}{s}{Colour.NORM}'


def init_logger():
    log = logging.getLogger('splice_graft')
    log.setLevel(LOG_LEVEL)
    fmt = logging.Formatter('{asctime} {levelname} {name}: {message}',
                            datefmt='%b %d %H:%M:%S',
                            style='{')
    hnd = logging.StreamHandler()
    hnd.setFormatter(fmt)
    log.addHandler(hnd)
    return log


log = init_logger()


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


def find(path: str, json: dict, expect_exists=False):
    """
    Gets an element by dot separated path in a nested dict-like object.
    """

    keys = path.split('.')
    ret = json
    for key in keys:
        elem = ret.get(key)
        if elem is None:
            if expect_exists:
                log.error('find() missing expected path %r', path)
                raise ValueError('find() did not find an expected path')
            # eprint('None in', ret, key)
            # eprint('CONTEXT', path, json)
            return None
        ret = elem
    return ret


def find_existing(path: str, json: dict) -> Any:
    res = find(path, json, expect_exists=True)
    return res


def get_user():
    QUERY = """
    {
      viewer {
        login
      }
    }
    """
    return find('data.viewer.login', graphql_query(QUERY))


def graphql_query(query, variables={}) -> dict:
    api_headers = {
        'Authorization': get_auth_header(),
    }
    body = {
        'query': query,
        'variables': variables,
    }
    return requests.post(API_ENDPOINT, json=body, headers=api_headers).json()


ResultType = TypeVar('ResultType')
U = TypeVar('U')


@dataclasses.dataclass
class Page(Generic[ResultType]):
    results: list[ResultType]
    """ results in this page """
    curs: str | None
    """ cursor for next items """

    def map(self, f: Callable[[list[ResultType]], list[U]]) -> 'Page[U]':
        return Page(f(self.results), self.curs)

    @classmethod
    def from_api(cls, page_info_path: str, api_resp: dict) -> 'Page':
        if errors := api_resp.get('errors'):
            log.error('Errors in graphql response: %r', errors)
            raise ValueError(f'Errors in graphql response')

        data = api_resp['data']
        page_info = find_existing(page_info_path, data)
        log.debug('pageInfo: %r', page_info)
        has_next = page_info['hasNextPage']
        next_curs = page_info['endCursor'] if has_next else None

        return Page(data, next_curs)


class Query(metaclass=abc.ABCMeta):
    QUERY: str

    def query(self, _after: Optional[str]) -> Page:
        raise NotImplemented()

    def __iter__(self):
        after = None
        while True:
            res = self.query(after)
            yield from res.results
            after = res.curs

            if not after:
                break


@dataclasses.dataclass
class PrInfo:
    title: str
    url: str
    changed_files: list[str]


PullRequestState = Literal["OPEN"] | Literal["CLOSED"] | Literal["MERGED"] | str


@dataclasses.dataclass
class QueryPrFiles(Query):
    owner: str
    name: str
    states: list[PullRequestState]

    QUERY = """
    query PrFiles($name: String = "", $owner: String = "", $after: String = null, $states: [PullRequestState!]) {
      repository(name: $name, owner: $owner) {
        pullRequests(after: $after, first: 50, states: $states) {
          pageInfo {
            endCursor
            hasNextPage
          }
          nodes {
            files(first: 100) {
              nodes {
                path
              }
              pageInfo {
                hasNextPage
              }
            }
            title
            url
          }
        }
      }
    }
    """

    def query(self, after: Optional[str]) -> Page[PrInfo]:
        PARAMS = {
            'name': self.name,
            'owner': self.owner,
            'after': after,
            'states': self.states
        }

        def mapper(data):
            prs = find_existing('repository.pullRequests.nodes', data)

            def make_pr_info(pr):
                info = PrInfo(pr['title'], pr['url'],
                              [f['path'] for f in pr['files']['nodes']])
                if find_existing('files.pageInfo.hasNextPage', pr):
                    log.warning(
                        'Processed PR with >100 files, some will not be considered: %r %s',
                        info.title, info.url)
                return info

            return [make_pr_info(pr) for pr in prs]

        res = Page.from_api('repository.pullRequests.pageInfo',
                            graphql_query(self.QUERY, PARAMS))
        return res.map(mapper)


@dataclasses.dataclass
class QueryRepos(Query):
    user: str
    any_branch: bool = False

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

    def query(self, after: Optional[str]) -> Page[dict]:
        VARIABLES = {
            'who': self.user,
            'curs': after,
        }
        res = graphql_query(self.QUERY, VARIABLES)

        res = Page.from_api('user.repositories.pageInfo', res)

        def mapper(data):
            repos = find_existing('user.repositories.nodes', data)
            assert repos
            # filter just repos that aren't fixed yet
            return [
                repo['nameWithOwner'] for repo in repos
                if (self.any_branch or find('defaultBranchRef.name', repo) ==
                    REPLACING_BRANCH) and not repo['isArchived']
            ]

        return res.map(mapper)


Matcher = Callable[[str], bool]
AllMatcher = Callable[[list[str]], bool]


def find_prs_for(owner: str, repo: str, states: list[PullRequestState],
                 matcher: AllMatcher) -> Generator[PrInfo, None, None]:
    return (pr for pr in QueryPrFiles(owner, repo, states)
            if matcher(pr.changed_files))


def cli_find_pr(args):

    def match_simple(pat: str) -> Matcher:
        pat = pat.removeprefix('/')

        def matcher(fname: str) -> bool:
            return fname == pat

        return matcher

    def match_re(pat: str) -> Matcher:
        comp = re.compile(pat)

        def matcher(fname: str) -> bool:
            return bool(comp.search(fname))

        return matcher

    STATUS_MAP = {
        'open': ['OPEN'],
        'closed': ['CLOSED'],
        'merged': ['MERGED'],
        'any': ['OPEN', 'CLOSED', 'MERGED'],
    }

    def flatten(t):
        return [item for sublist in t for item in sublist]

    states = flatten(STATUS_MAP[v] for v in args.status)

    if len(states) == 0:
        states = ['OPEN']

    MATCHERS = {
        'simple': match_simple,
        're': match_re,
    }

    matchers_per_file = [
        MATCHERS[args.mode](pat) for pat in args.files_touched
    ]
    matcher = lambda files: any(
        all(m(f) for m in matchers_per_file) for f in files)

    owner, repo, *rest = args.repo.split('/')
    if len(rest) != 0:
        raise ValueError('Provided owner/repo has the wrong number of fields')

    OUTPUT_FORMAT = textwrap.dedent("""
        {title}
        {url}
        {files_block}""")
    for pr in find_prs_for(owner, repo, states, matcher):
        files_block = '\n'.join(f'- {fname}' for fname in pr.changed_files)
        print(
            OUTPUT_FORMAT.format(title=Colour.bold(pr.title),
                                 url=pr.url,
                                 files_block=files_block))


def cli_list(args):
    user = args.user
    if not user:
        user = get_user()

    for repo in QueryRepos(user, any_branch=args.all):
        print(repo)


def get_branch_info(repo, branch):
    """
    Returns (repoID, branchTipOID) for a given repo and branch. The given `branch`
    does not need to be fully qualified.
    """

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
    return (find('data.repository.id',
                 res), find('data.repository.ref.target.oid', res))


def new_ref(repo_id, branch, tip_oid):
    """
    Creates a new git ref.

    Parameters:
    * repo_id -- the opaque id for the repo, from `get_branch_info()`
    * branch  -- fully qualified branch name i.e. refs/heads/...
    * tip_oid -- the git object ID of the tip of the new branch
    """

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


def set_default_branch(repo_path: str, branch: str) -> requests.Response:
    """
    Sets the default branch of `repo_path` to `branch`. GitHub does wacky stuff if
    you give it a canonical branch name.
    """

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
    return requests.patch('{}/repos/{}'.format(API_BASE, repo_path),
                          json=body,
                          headers=HEADERS)


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
                eprint('Error making a new branch in {}: {}'.format(
                    repo_path, err['message']))

        resp = set_default_branch(repo_path, new_branch_name)
        if resp.status_code != 200:
            eprint('Got error updating default branch in {}: {}'.format(
                repo_path, resp.json()))
        eprint('Done', repo_path)


def cli_set(args: argparse.Namespace):
    body = {
        k: v
        for k, v in args.__dict__.items() if k != 'cmd' and v is not None
    }
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
    raise ValueError(
        f'Could not parse {s!r} as boolean, try yes/y/true/on or no/n/false/off'
    )


def main():
    ap = argparse.ArgumentParser()
    sps = ap.add_subparsers()

    def fail(*args):
        ap.print_help()
        sys.exit(1)

    ap.set_defaults(cmd=fail)

    list_parser = sps.add_parser(
        'list',
        help='List non-archived repositories with the `master` default branch')
    list_parser.add_argument('user',
                             help='User to find repos of',
                             nargs='?',
                             default=None)
    list_parser.add_argument('--all',
                             '-a',
                             help='List repos with any default branch',
                             action='store_true',
                             default=False)
    list_parser.set_defaults(cmd=cli_list)

    fix_parser = sps.add_parser(
        'fix', help='Rename the default branch for a (stdin) list of repos')
    fix_parser.add_argument('new_branch',
                            help='New branch name',
                            nargs='?',
                            default='main')
    fix_parser.set_defaults(cmd=cli_fix)

    find_pr_parser = sps.add_parser(
        'find_pr', help='Finds a pull request touching the specified files')
    find_pr_parser.add_argument('repo', help='Repo name to find prs on')
    find_pr_parser.add_argument('files_touched',
                                help='Files touched by the PR',
                                nargs='*')
    find_pr_parser.add_argument('--mode',
                                '-m',
                                help='Match mode',
                                choices=('simple', 're'),
                                default='simple')
    find_pr_parser.add_argument('--status',
                                '-s',
                                help='PR status',
                                choices=('open', 'closed', 'merged', 'any'),
                                action='append')
    find_pr_parser.set_defaults(cmd=cli_find_pr)

    set_parser = sps.add_parser(
        'set',
        help='Sets some attributes on a set of repositories (from stdin)')
    set_parser.add_argument('--allow-squash-merge',
                            help='Permit squash '
                            'merge on this repo',
                            default=None,
                            type=parse_bool)
    set_parser.add_argument('--allow-rebase-merge',
                            help='Permit rebase '
                            'merge on this repo',
                            default=None,
                            type=parse_bool)
    set_parser.add_argument('--allow-merge-commit',
                            help='Permit merge '
                            'commits on this repo',
                            default=None,
                            type=parse_bool)
    set_parser.set_defaults(cmd=cli_set)

    args = ap.parse_args()
    args.cmd(args)


if __name__ == '__main__':
    main()
