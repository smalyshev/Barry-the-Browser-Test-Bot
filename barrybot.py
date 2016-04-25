#!/usr/bin/env python

'''
Copyright [2013] [Jon Robson]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

See the License for the specific language governing permissions and
limitations under the License.
'''
import urllib2
import json
import subprocess
import argparse
import sys
import pprint

def run_shell_command( args, pre_pipe_args=None, verbose = False ):
    """
    run_shell_command(['echo', 'hi']) runs 'echo hi'
    run_shell_command(['grep', 'hi'], ['cat', 'hi.txt']) runs 'cat hi.txt | grep hi'
    """
    cmd = " ".join( args )
    if verbose:
        print "Running `%s`" %cmd
    sys.stdout.flush()
    if pre_pipe_args:
        pre_pipe = subprocess.Popen(pre_pipe_args, stdout=subprocess.PIPE)
        process = subprocess.Popen(args, stdin=pre_pipe.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        process = subprocess.Popen( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
    output = [];
    error = [];
    for line in iter(process.stdout.readline, ''):
        if verbose:
            sys.stdout.write(line)
            sys.stdout.flush()
        output.append(line)
    for line in iter(process.stderr.readline, ''):
        sys.stderr.write(line)
    process.wait()
#    output, error = process.communicate()
    return "\n".join(output), process.returncode > 0

def run_maintenance_scripts( mediawikipath, verbose = False ):
    args = ['cd', mediawikipath, '&&',
        'php', 'maintenance/update.php' ]
    output, error = run_shell_command( args, verbose=verbose )

def update_code_to_master( paths, verbose = False ):
    print "Updating to latest code..."
    for path in paths:
        args = ['cd', path, '&&',
            # Stuff might be dirty
            'git', 'stash', '&&',
            'git', 'checkout', 'master', '&&',
            # Update code
            'git', 'pull', 'origin', 'master' ]
        output, error = run_shell_command( args, verbose=verbose )

def get_pending_changes( project, user, verbose = False ):
    url = "https://gerrit.wikimedia.org/r/changes/?q=project:%s+(label:Verified>=0)+status:open+label:Code-Review=0,user=%s+NOT+age:2w+branch:master&O=1"%(project,user)
    if verbose:
        print "Request %s"%url
    req = urllib2.Request(url)
    req.add_header('Accept',
                   'application/json,application/json,application/jsonrequest')
    req.add_header('Content-Type', "application/json; charset=UTF-8")
    resp, data = urllib2.urlopen(req)
    data = json.loads(data)
    return data

def checkout_commit( path, changeid, verbose = False ):
    print "Preparing to test change %s..." % changeid
    args = ["cd", path, "&&",
        # might be in a dirty state
        'git', 'stash', '&&',
        'git', 'checkout', 'master', '&&',
        "git", "review", "-d", changeid
     ]
    output, error = run_shell_command( args, verbose=verbose )
    # get the latest commit
    args = [ "cd", path, "&&",  "git", "rev-parse", "HEAD" ]
    output, error = run_shell_command( args, verbose=verbose )
    commit = output.strip()
    return commit

def check_dependencies( mediawikipath, pathtotest, verbose = False ):
    output, error = run_shell_command([
        "cd", pathtotest, "&&",
        "git", "log", "-1", "|",
	"grep", "'^    Depends-On:'", "|",
	"cut", "-d", ':', '-f', '2-'
    ], verbose=verbose)
    for line in output.strip(' ').split("\n"):
        if line.strip() == '':
            continue
        commit_id = line.strip()
        # bold assumption the commit it is a core id
        run_shell_command(["cd", mediawikipath, "&&", "git", "review", "-d", commit_id], verbose=verbose)

def bundle_install( path, verbose = False ):
    print 'Running bundle install'
    args = ['cd', path, '&&',
        'cd', 'tests/browser/', '&&',
        'bundle', 'install' ]
    output, error = run_shell_command( args, verbose=verbose )

def run_browser_tests( path, tag = None, verbose = False, dry_run = False, fullog = None ):
    print 'Running browser tests...'
    args = ['cd', path, '&&',
        'cd', 'tests/browser/', '&&',
        'bundle', 'exec', 'cucumber', 'features/',
    ]
    
    if fullog:
        args.extend( [ '--format', 'pretty', '--no-color', '--out', fullog ] )
        
    if dry_run:
        args.extend( [ '--format', 'rerun' ] )
        
    if tag:
        if tag[0] != '@' and tag[0]  != '~':
            tag = '@' + tag
        args.extend( [ '--tags', tag ] )

    output, error = run_shell_command( args, verbose=verbose )

    if error:
       is_good = False
    else:
        is_good = True
        output = 'Cindy says good job. Keep it up.'
    return is_good, output

def do_review( pathtotest, commit, is_good, msg, action, verbose = False, user = None ):
    print "Posting to Gerrit..."
    args = [ 'cd', pathtotest, '&&',
        'ssh', '-p 29418',
        'cindythebrowsertestbot@gerrit.wikimedia.org', 'gerrit', 'review' ]
    if action == 'verified':
        if is_good:
            score = '+2'
        else:
            score = '-2'
        args.extend( ['--' + action, score ] )
    else:
        if is_good:
            score = '+1'
        else:
            score = '-1'
        args.extend( ['--' + action, score ] )

    if msg:
        args.extend( [ '--message', "\"'" + msg.replace( '"', '' ).replace( "'", '' ) + "'\"" ] )
    args.append( commit )
    # Turn on when you trust it.
    output, error = run_shell_command( args, verbose=verbose )

def get_parser_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', help='Name of project e.g. mediawiki/extension/Gather', type=str)
    parser.add_argument('--core', help='Absolute path to core e.g /git/core', type=str)
    parser.add_argument('--test', help='Absolute path that corresponds to project to be tested. e.g /git/core', type=str)
    parser.add_argument('--dependencies', help='Absolute path to a dependency e.g /git/core/extensions/MobileFrontend', type=str, nargs='+')
    parser.add_argument('--tag', help='A tag to run a subset of tests. e.g. `wip`', type=str)
    parser.add_argument('--noupdates', help='This will do no review but will tell you what it is about to review', type=bool)
    parser.add_argument('--review', help='This will post actual reviews to Gerrit. Only use when you are sure Barry is working.', type=bool)
    parser.add_argument('--verify', help='This will post actual reviews to Gerrit. Only use when you are sure Barry is working.', type=bool)
    parser.add_argument('--verbose', help='Advanced debugging.', type=bool)
    parser.add_argument('--user', help='The username of the bot which will do the review.', type=str)
    parser.add_argument('--paste', help='This will post failed test results to phabricator and share the url in the posted review.', type=bool)
    parser.add_argument('--nobundleinstall', help='When set skip the bundle install step.', type=bool)
    parser.add_argument('--successmsg', help='Defines the message to show for successful commits', type=str, default='I ran browser tests for your patch and everything looks good. Merge with confidence\!')
    parser.add_argument('--errormsg', help='Defines the message to show for bad commits', type=str, default='I ran browser tests for your patch and there were some errors you might want to look into:\n%s')
    parser.add_argument('--pretest', help="This command will be executed just before running the tests", action='append', default=[])
    return parser

def get_paste_url(text):
    """ paste text into Phabricator
    Return paste URL
    """
    output, error = run_shell_command(['arc', 'paste'], ['echo', text])
    # output looks something like "P899: https://phabricator.wikimedia.org/P899"
    return output.split(': ')[1].strip()

def get_username( args ):
    if args.user:
        user = args.user
    else:
        user, code = run_shell_command( [ 'git config --global user.name' ] )
        user = user.strip()
    return user

def get_paths( args ):
    if args.dependencies:
        dependencies = args.dependencies
    else:
        dependencies = []
    paths = [ args.core, args.test ]
    paths.extend( dependencies )
    return paths

def get_gerrit_action( args ):
    if args.review:
        return 'code-review'
    else:
        return 'verified'

def watch( args ):
    verbose = args.verbose

    paths = get_paths( args )
    print "Searching for patches to review..."
    user = get_username( args )
    changes = get_pending_changes( args.project, user, verbose )
    if len( changes ) == 0:
        print "No changes."

    for change in changes:
        print "Testing %s..."%change['subject']
        test_change( change["_number"], args )

def test_change( change_id, args ):
    action = get_gerrit_action( args )
    paths = get_paths( args )
    user = get_username( args )
    if not args.noupdates:
        update_code_to_master( paths, args.verbose )
        run_maintenance_scripts( args.core, args.verbose )
    commit = checkout_commit( args.test, str( change_id ), args.verbose )
    if not args.noupdates and not args.nobundleinstall:
        check_dependencies( args.core, args.test, args.verbose )
        run_maintenance_scripts( args.core, args.verbose )
        bundle_install( args.test, args.verbose )
        pprint.pprint( args.pretest )
        run_shell_command( [ " && ".join( args.pretest ) ], verbose=args.verbose )
    is_good, output = run_browser_tests( args.test, args.tag, args.verbose, not args.paste, '/tmp/cindy_run.%s.log' % str(change_id) )
    if args.verbose:
        print output
    if args.paste:
        # Add extract protection for empty output string and error code.
        output = output.strip()
        if not is_good and output:
            print 'Pasting commit %s with (is good = %s)..' %(commit, is_good)
            output = "[%s]\n" + output
            paste_url = get_paste_url(output)
            print "Result pasted to %s"%paste_url
    else:
        paste_url = None

    if is_good:
        review_msg = args.successmsg
    else:
        if paste_url:
            review_msg = args.errormsg%paste_url
        else:
            review_msg = args.errormsg%output
    if action:
        print 'Reviewing commit %s with (is good = %s)..' %( commit, is_good )
        do_review( args.test, commit, is_good, review_msg, action, args.verbose, user )

if __name__ == '__main__':
    parser = get_parser_arguments()
    args = parser.parse_args()
    if not args.project or not args.core or not args.test:
        print 'Project, core and test are needed.'
        sys.exit(1)

    pprint.pprint( args.pretest )
    watch( args )

