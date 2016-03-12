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

def run_shell_command( args ):
    cmd = " ".join( args )
    print "running cmd: %s" % cmd
    sys.stdout.flush()
    process = subprocess.Popen( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
    output = [];
    error = [];
    for line in iter(process.stdout.readline, ''):
        sys.stdout.write(line)
        sys.stdout.flush()
        output.append(line)
    for line in iter(process.stderr.readline, ''):
        sys.stderr.write(line)
        error.append(line)
    #output, error = process.communicate()
    #if error and not error.isspace():
    #  print "error: %s" % error
    return "\n".join(output), "\n".join(error)

def run_maintenance_scripts( mediawikipath ):
    args = ['cd', mediawikipath, '&&',
        'php', 'maintenance/update.php' ]
    run_shell_command(args)

def update_code_to_master( paths ):
    print "Updating to latest code..."
    for path in paths:
        args = ['cd', path, '&&',
            'git', 'checkout', 'master', '&&',
            # Stuff might be dirty
            'git', 'stash', '&&',
            # Update code
            'git', 'pull', 'origin', 'master' ]
        run_shell_command(args)

def get_pending_changes( project, user ):
    url = "https://gerrit.wikimedia.org/r/changes/?q=project:%s+(label:Verified>=0)+status:open+label:Code-Review=0,user=%s+NOT+age:2w+branch:master&O=1"%(project,user)
    print url
    req = urllib2.Request(url)
    req.add_header('Accept',
                   'application/json,application/json,application/jsonrequest')
    req.add_header('Content-Type', "application/json; charset=UTF-8")
    resp, data = urllib2.urlopen(req)
    data = json.loads(data)
    return data

def checkout_commit( path, changeid ):
    print "Preparing to test change %s..." % changeid
    args = ["cd", path, "&&",
        "git", "review", "-d", changeid
     ]
    run_shell_command(args)
    # get the latest commit
    args = [ "cd", path, "&&",  "git", "rev-parse", "HEAD" ]
    output, error = run_shell_command(args)
    commit = output.strip()
    return commit

def check_dependencies( mediawikipath, pathtotest ):
    output, error = run_shell_command([
        "cd", pathtotest, "&&",
        "git", "log", "-1", "|", 
	"grep", "'^    Depends-on:'", "|",
	"cut", "-d", ':', '-f', '2-'
    ])
    for line in output.strip(' ').split("\n"):
        if line.strip() == '':
            continue
        commit_id = line.strip()
        # bold assumption the commit it is a core id
        run_shell_command(["cd", mediawikipath, "&&", "git", "review", "-d", commit_id])

def bundle_install( path ):
    print 'Running bundle install'
    args = ['cd', path, '&&',
        'cd', 'tests/browser/', '&&',
        'bundle', 'install' ]
    run_shell_command(args)

def run_browser_tests( path, tag = None ):
    print 'Running browser tests...'
    args = ['cd', path, '&&',
        'cd', 'tests/browser/', '&&',
        'bundle', 'exec', 'cucumber', 'features/', 
        '--format', 'rerun', '--tags', '~@expect_failure'
    ]
    #if tag:
    #    args.extend( [ '--tags', '@' + tag ] )

    output, error = run_shell_command(args)
    # Make this execute cucumber
    if output:
        is_good = False
    else:
        is_good = True
        output = 'Cindy says good job. Keep it up.'
    return is_good, output

def do_review( pathtotest, commit, is_good, msg, action ):
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
    run_shell_command(args)


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
    parser.add_argument('--user', help='The username of the bot which will do the review.', type=str, default='BarryTheBrowserTestBot')
    parser.add_argument('--pretest', help="This command will be executed just before running the tests", action='append', default=[])
    return parser

def watch( project, user, mediawikipath, pathtotest, tag = None, pretest=[], dependencies=[], noupdates = False, action = None ):
    paths = [ mediawikipath, pathtotest ]
    paths.extend( dependencies )
    print "Searching for patches to review..."
    changes = get_pending_changes( project, user )
    if len( changes ) == 0:
        print "No changes."

    for change in changes:
        print "Testing %s..."%change['subject']
        if not noupdates:
            update_code_to_master( paths )
        commit = checkout_commit( pathtotest, str(change["_number"]) )
        if not noupdates:
            check_dependencies( mediawikipath, pathtotest )
            run_maintenance_scripts( mediawikipath )
            bundle_install( pathtotest )
            import pprint
            pprint.pprint(pretest)
            run_shell_command( [ " && ".join( pretest ) ] )
        is_good, output = run_browser_tests( pathtotest, tag )
        print 'Reviewing commit %s with (is good = %s)..' %( commit, is_good )
        print output
        if action:
            do_review( pathtotest, commit, is_good, output, action )

if __name__ == '__main__':
    parser = get_parser_arguments()
    args = parser.parse_args()
    if not args.project or not args.core or not args.test:
        print 'Project, core and test are needed.'
        sys.exit(1)
    if args.dependencies:
        deps = args.dependencies
    else:
        deps = []
    if args.review:
        action = 'code-review'
    else:
        action = 'verified'

    import pprint;
    pprint.pprint(args.pretest)
    
    watch( args.project,
        args.user,
        args.core,
        args.test,
        args.tag,
        args.pretest,
        deps, args.noupdates, action )

