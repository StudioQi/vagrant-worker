# -=- encoding: utf-8 -=-
import sys
from config import JETO_PATH
sys.path.append(JETO_PATH)

from rq import Queue, Worker, Connection
from rq import get_current_job
from rq.decorators import job
from sh import git
import os
import logging
import sh
from sh import ErrorReturnCode, errno
import re
import json
import time
from redis import Redis
import requests
redis_conn = Redis()

from jeto.models.host import Host

basedir = os.path.abspath(os.path.dirname(__file__))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(
    '/var/log/vagrant-worker/debug.log'.format(basedir)
)
# formatter = logging.Formatter('%(levelname) -10s %(asctime)s\
#    %(module)s:%(lineno)s %(funcName)s %(message)s')

# handler.setFormatter(formatter)
logger.addHandler(handler)
current_job = None


def resetEnv(host=None, environment=None):
    new_env = os.environ.copy()
    new_env['HOME'] = '/root'
    if host:
        new_env['VAGRANT_DEFAULT_PROVIDER'] = host.provider
    if environment:
        new_env['ENVIRONMENT'] = environment

    if host:
        for param in host.params.splitlines():
            if param != '' and '=' in param:
                key, value = param.split('=')
                new_env[key] = value.strip().replace("'", '').replace('"', '')

    return new_env


@job('low', connection=redis_conn, timeout=40)
def ip(path, host, environment, machineName='default'):
    logger.debug('Getting IP from vagrant machine {}'.format(machineName))
    new_env = resetEnv(host, environment)
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        machineType = sh.vagrant('status', machineName, _env=new_env)

        if 'stopped' not in machineType:
            if 'virtualbox' in machineType:
                ips = sh.vagrant('ssh', machineName, '-c', 'ip addr list eth1',
                                 _env=new_env)
                ips = str(ips)
                search = re.match(r'.* inet (.*)/24 brd',
                                  ips.stdout.replace('\n', ''))

                if search:
                    ip = search.group(1)
            elif 'lxc' in machineType or 'vsphere' in machineType:
                ips = sh.vagrant('ssh-config', machineName, _env=new_env)
                ips = str(ips)
                search = re.findall('HostName (.*)\n', ips, re.M)
                if search:
                    ip = search[0]
                # logger.debug(ip)

    except:
        logger.error('Unable to connect to machine to it\'s IP :: {}'
                     .format(path))

    os.chdir(old_path)
    return ip


@job('high', connection=redis_conn, timeout=600)
def sync(path, git_reference):
    new_env = resetEnv()
    logger.debug('Syncing {}'.format(path))
    old_path = os.getcwd()
    jobid = get_current_job().id
    _open_console(jobid)

    try:
        os.chdir(path)

        _log_console(jobid, 'Syncing project with Git.\n')
        _l = lambda line: _log_console(jobid, str(line))
        git.fetch(_out=_l, _err=_l, _env=new_env).wait()
        git.reset(
            '--hard',
            'origin/{}'.format(git_reference),
            _out=_l,
            _err=_l,
            _env=new_env).wait()
        git.submodule(
            'sync',
            _out=_l,
            _err=_l,
            _env=new_env).wait()
        git.submodule(
            'update',
            _out=_l,
            _err=_l,
            _env=new_env).wait()

    except:
        logger.error(
            'Failed to sync project at {}'.format(path),
            exc_info=True
        )

    _close_console(jobid)

    os.chdir(old_path)


@job('high', connection=redis_conn, timeout=1200)
def run(path, environment, host, machineName):
    old_path = os.getcwd()
    new_env = resetEnv(host=host, environment=environment)

    jobid = get_current_job().id
    _open_console(jobid)

    status = _get_status(path, host, environment)
    _l = lambda line: _log_console(jobid, str(line))
    if 'not created' not in status and host.provider not in status:
        try:
            logger.debug('Destroying machine {} for provider {}'
                         .format(path, host.provider))
            os.chdir(path)
            sh.vagrant('destroy', _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
            os.chdir(old_path)

        except:
            logger.error('Failed to destroy machine {}'.format(path))

    try:
        os.chdir(path)

        if machineName != '':
            sh.vagrant('up', machineName,
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
        else:
            sh.vagrant('up', _env=new_env,
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l).wait()
        os.chdir(old_path)

    except ErrorReturnCode, e:
        for line in e.message.splitlines():
            logger.debug(line)
            _log_console(jobid, line)

    _close_console(jobid)

    return json.dumps(_get_status(path, host, environment))


@job('high', connection=redis_conn, timeout=1200)
def provision(path, environment, machineName, host):
    new_env = resetEnv(host, environment)
    # logger.debug('Running provision on {} with env {}'
    #            .format(path, environment))
    old_path = os.getcwd()
    jobid = get_current_job().id
    try:
        os.chdir(path)
        _open_console(jobid)
        if machineName != '':
            _l = lambda line: _log_console(jobid, str(line))
            sh.vagrant('provision', machineName,
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
        else:
            _l = lambda line: _log_console(jobid, str(line))
            sh.vagrant('provision',
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
    except:
        logger.error('Failed to provision machine at {}'.format(path),
                     exc_info=True)
    _close_console(jobid)
    os.chdir(old_path)
    return json.dumps(_get_status(path, host, environment))


@job('high', connection=redis_conn, timeout=1200)
def extract(path, archive_url, host):
    """Fetch a tgz archive and extract it to the desired path"""
    # new_env = resetEnv(host)
    # TODO: check file type
    types = {
        'application/zip': sh.unzip,
        'application/x-tar': lambda f: sh.tar('-xf', f)
        }
    import mimetypes
    filename = os.path.basename(archive_url)
    file_type = mimetypes.guess_type(archive_url)[0]
    logger.debug('Extracting {} - {} - {} to {}'
                 .format(archive_url, filename, file_type, path))
    old_path = os.getcwd()
    tmp_file = '/tmp/{}'.format(filename)
    download = requests.get(archive_url, stream=True)
    if file_type not in types:
        return
    try:
        os.makedirs(path)
        os.chdir(path)
        with open(tmp_file, 'wb') as f:
            for data in download.iter_content(5120000):
                f.write(data)
            f.close()
        types[file_type](tmp_file)
        # Ensure the Vagrantfile is in the destination path
        # ignore the first folder if necessary
        has_one_folder = os.listdir(path)
        if len(has_one_folder) == 1:
            sh.mv(sh.glob(os.path.join(path, has_one_folder[0], '*')),
                  os.path.join(path, '.'))
        os.remove(tmp_file)
        logger.debug('{} {}'.format(
            archive_url,
            path
        ))
    except:
        logger.error('Failed to extract project at {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)


@job('high', connection=redis_conn, timeout=1200)
def clone(path, git_address, git_reference, host):
    new_env = resetEnv(host)
    logger.debug('Cloning {} with git_reference {} at {}'
                 .format(git_address, git_reference, path))
    old_path = os.getcwd()
    try:
        os.makedirs(path)
        os.chdir(path)
        git_reference = git_reference.replace('tags/', '')

        git.clone(
            git_address,
            '.',
            '--recursive',
            '--branch',
            git_reference,
            '--depth',
            1,
            _env=new_env
        )
        logger.debug('{} {} {} {} {} {} {}'.format(
            git_address,
            '.',
            '--recursive',
            '--branch',
            git_reference,
            '--depth',
            1
        ))
    except:
        logger.error('Failed to clone project at {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)


@job('high', connection=redis_conn, timeout=1200)
def stop(path, machineName, host, environment):
    new_env = resetEnv(host, environment)
    logger.debug('Bring down {}'.format(path))
    old_path = os.getcwd()
    jobid = get_current_job().id
    try:
        os.chdir(path)
        _open_console(jobid)
        if machineName != '':
            _l = lambda line: _log_console(jobid, str(line))
            sh.vagrant('halt', machineName,
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
        else:
            _l = lambda line: _log_console(jobid, str(line))
            sh.vagrant('halt',
                       _ok_code=[0, 1, 2],
                       _out=_l, _err=_l,
                       _env=new_env).wait()
    except:
        logger.error('Failed to shut down machine {}'.format(path),
                     exc_info=True)

    _close_console(jobid)
    os.chdir(old_path)
    # logger.debug('Done bring down {}'.format(path))
    return json.dumps(_get_status(path, host, environment))


@job('high', connection=redis_conn, timeout=1200)
def destroy(path, host, environment):
    new_env = resetEnv(host, environment)
    # old current working dir won't exist after destroy
    # keep parent's path
    old_path = os.path.dirname(
                    os.path.dirname(os.getcwd()))
    try:
        if os.path.isdir(path):
            os.chdir(path)
            sh.vagrant('destroy', '--force', _env=new_env)
            os.chdir(old_path)
            sh.rm('-rf', path)

    except:
        logger.error('Failed to destroy machine {}'.format(path),
                     exc_info=True)

    return json.dumps(_get_status(path, host, environment))


@job('low', connection=redis_conn, timeout=60)
def status(path, host, environment):
    status = {}
    try:
        status['vagrant'] = _get_status(path, host, environment)
        # logger.debug(status)
    except:
        return json.dumps({'msg': 'error getting status'})

    status['jeto_infos'] = _read_jeto_file(path)

    return json.dumps(status)


@job('high', connection=redis_conn, timeout=1200)
def rsync(path, host, machineName=None):
    new_env = resetEnv(host)
    old_path = os.getcwd()
    os.chdir(path)
    try:
        jobid = get_current_job().id
        _open_console(jobid)
        _log_console(
            jobid,
            'Running rsync on machine {}.\n'.format(machineName)
        )

        _l = lambda line: _log_console(jobid, str(line))

        if machineName is not None:
            sh.vagrant('rsync', machineName,
                       _out=_l,
                       _err=_l,
                       _ok_code=[0, 1, 2],
                       _env=new_env).wait()
        else:
            sh.vagrant('rsync',
                       _out=_l,
                       _err=_l,
                       _ok_code=[0, 1, 2],
                       _env=new_env).wait()
        _log_console(
            jobid,
            'rsync is done running on machine {}.\n'.format(machineName))
        _close_console(jobid)
    except:
        return json.dumps({'msg': 'error trying to run vagrant rsync'})
    os.chdir(old_path)
    return json.dumps({'msg': 'rsync done'})


@job('low', connection=redis_conn, timeout=60)
def get_git_references(git_address, project_id):
    resetEnv()
    os.chdir('/tmp')
    logger.debug('Getting git ref : git ls-remote {}'
                 .format(git_address))
    fullRefs = git('ls-remote', git_address)
    fullRefs = fullRefs.splitlines()

    ref = [refs.split('\t')[1].replace('refs/', '').replace('heads/', '')
           for refs in fullRefs]

    ref = [refs for refs in ref if refs != 'HEAD']

    return json.dumps(ref)


@job('high', connection=redis_conn, timeout=1200)
def run_script(path, host, environment, script, machineName='default'):
    new_env = resetEnv(host, environment)
    old_path = os.getcwd()
    try:
        logger.debug(
            'Running script {} on machine {}'.format(script, machineName)
        )
        jeto_infos = _read_jeto_file(path)
        all_scripts = jeto_infos.get('scripts')
        logger.debug(all_scripts)
        if all_scripts.get(script, None) and\
                all_scripts.get(script, None).get('command', None):
            os.chdir(path)
            jobid = get_current_job().id
            _open_console(jobid)
            _log_console(
                jobid,
                'Running {} on machine {}.\n'.format(script, machineName)
            )

            _l = lambda line: _log_console(jobid, str(line))

            sh.vagrant('ssh', machineName, '-c',
                       all_scripts.get(script).get('command'),
                       _out=_l,
                       _err=_l,
                       _ok_code=[0, 1, 2],
                       _env=new_env).wait()
            _log_console(
                jobid,
                '{} is done running on machine {}.\n'.format(
                    script, machineName))
            _close_console(jobid)
    except:
        e = sys.exc_info()
        logger.error(
            'Failed to run script {} of the machine {}'.format(script, path),
            exc_info=True
        )
        _log_console(
            jobid,
            'Failed to run script {} of the machine {}\n Exception: {}.\n'.format(
                script, machineName, e))
    _close_console(jobid)

    os.chdir(old_path)


def _get_status(path, host, environment):
    new_env = resetEnv(host, environment)
    old_path = os.getcwd()
    statuses = None
    try:
        jobid = get_current_job().id
        os.chdir(path)
        _open_console(jobid, private=True)
        _l = lambda line: _log_console(jobid, str(line), private=True)
        sh.vagrant('status', '--machine-readable', '--debug',
                   _out=_l,
                   _ok_code=[0, 1, 2],
                   _env=new_env).wait()
        _close_console(jobid, private=True)

        statuses = _read_console(jobid, private=True)
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)
    return statuses


def _open_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    return redis_conn.set(job_key, '#BEGIN#\n')


def _read_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    return redis_conn.get(job_key)


def _log_console(jobId, line, private=False, test=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)

    console = redis_conn.get(job_key)
    if console is None:
        console = ''

    if test:
        logger.debug(line)
    redis_conn.set(job_key, console + line)
    expires = int(time.time()) + (5 * 60) + 10
    redis_conn.expireat(job_key, expires)


def _close_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    console = redis_conn.get(job_key)
    if console is None:
        console = ''
    # logger.debug(console)
    return redis_conn.set(job_key, console + '\n#END#\n')


def _read_jeto_file(path):
    if os.path.isfile(path + '/jeto.json'):
        fileHandler = open(path + "/jeto.json")
        jetoInfos = json.load(fileHandler)
        fileHandler.close()
        return jetoInfos
    else:
        return ''


if __name__ == '__main__':
    # Tell rq what Redis connection to use
    with Connection():
        q = map(Queue, sys.argv[1:]) or [Queue()]
        Worker(q).work()
