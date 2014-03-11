from daemon import Daemon
import os
import gearman
from vagrant import Vagrant
import logging
import sys
import sh
import re
import json

basedir = os.path.abspath(os.path.dirname(__file__))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('{}/vagrant-worker.log'.format(basedir))
formatter = logging.Formatter('%(levelname) -10s %(asctime)s %(module)s:%(lineno)s %(funcName)s %(message)s')

handler.setFormatter(formatter)
logger.addHandler(handler)


class App(Daemon):
    def run(self):
        while True:
            for i in range(4):
                gm_worker = gearman.GearmanWorker(['localhost'])
                gm_worker.set_client_id('vagrant-worker-{}'
                                        .format(os.getpid(), i))
                logger.debug('Registering gearman vagrant-worker-{}'
                             .format(os.getpid(), i))
                gm_worker.register_task('start', run)
                gm_worker.register_task('stop', stop)
                gm_worker.register_task('status', status)
                gm_worker.register_task('ip', ip)
                gm_worker.register_task('destroy', destroy)
                gm_worker.work()


def ip(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Getting IP from vagrant machine')
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        machineType = sh.vagrant('status')
        logger.debug(machineType)

        if 'stopped' not in machineType:
            if 'virtualbox' in machineType:
                ips = sh.vagrant('ssh', '-c', 'ip addr list eth1')
                ips = str(ips)
                search = re.match(r'.* inet (.*)/24 brd', ips.stdout.replace('\n', ''))

                if search:
                    ip = search.group(1)
            elif 'lxc' in machineType:
                ips = sh.vagrant('ssh-config')
                ips = str(ips)
                search = re.findall('HostName (.*)\n', ips, re.M)
                if search:
                    ip = search[0]
                logger.debug(ip)

    except:
        logger.error('Unable to connect to machine to it\'s IP :: {}'
                     .format(path))

    os.chdir(old_path)
    return ip


def run(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    eth = _get_eth(gearman_job)
    environment = _get_environment(gearman_job)
    provider = _get_provider(gearman_job)
    old_path = os.getcwd()

    logger.debug('Bring up {} with eth {} and environment set to {} with provider {}'
                 .format(path, eth, environment, provider))

    status = _get_status(path)
    if 'not created' not in status and provider not in status:
        logger.debug('Machine already created with another provider,\
destroying first')
        try:
            os.chdir(path)
            sh.vagrant('destroy')
            os.chdir(old_path)

        except:
            logger.error('Failed to destroy machine {}'.format(path))

        logger.debug('Done destroying')

    try:
        os.chdir(path)
        os.environ['ETH'] = eth
        os.environ['ENVIRONMENT'] = environment
        os.environ['VAGRANT_DEFAULT_PROVIDER'] = provider
        sh.vagrant('up')
        os.chdir(old_path)
    except:
        logger.error('Failed to bring up machine {}'.format(path),
                     exc_info=True)
    logger.debug('Done bring up {}'.format(path))

    return json.dumps(_get_status(path))


def stop(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Bring down {}'.format(path))

    vagrant = Vagrant(path)
    try:
        vagrant.halt()
    except:
        logger.error('Failed to shut down machine {}'.format(path),
                     exc_info=True)

    logger.debug('Done bring down {}'.format(path))
    return json.dumps(_get_status(path))


def destroy(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Destroying {}'.format(path))

    vagrant = Vagrant(path)
    try:
        vagrant.destroy()
    except:
        logger.error('Failed to destroy machine {}'.format(path),
                     exc_info=True)

    logger.debug('Done destroying {}'.format(path))
    return json.dumps(_get_status(path))


def status(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Asking Status for {}'.format(path))
    try:
        status = _get_status(path)
    except:
        return json.dumps()

    logger.debug('Status : {} :: {}'.format(status, path))
    return json.dumps(status)


def _get_path(gearman_job):
    data = json.loads(gearman_job.data)
    return data['path']


def _get_eth(gearman_job):
    data = json.loads(gearman_job.data)
    return data['eth']


def _get_environment(gearman_job):
    data = json.loads(gearman_job.data)
    return data['environment']


def _get_provider(gearman_job):
    data = json.loads(gearman_job.data)
    if 'provider' in data:
        return data['provider']
    return None


def _get_status(path):
    old_path = os.getcwd()
    try:
        os.chdir(path)
        statuses = str(sh.vagrant('status'))
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)
    return statuses


if __name__ == '__main__':
    #app = App('/var/run/vagrant-worker.pid'.format(os.getpid()))
    app = App('{}/pids/vagrant-worker-{}.pid'.format(basedir, os.getpid()))
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            logger.info('Starting vagrant-worker service')
            app.start()
        elif 'stop' == sys.argv[1]:
            logger.info('Stopping vagrant-worker service')
            app.stop()
        elif 'restart' == sys.argv[1]:
            logger.info('Restart vagrant-worker service')
            app.restart()
        elif 'run' == sys.argv[1]:
            logger.info('Run debug vagrant-worker service')
            app.run()
        else:
            print 'Unknown command'
            sys.exit(0)
    else:
        print 'usage: {} start|stop|restart|run '.format(sys.argv[0])
        sys.exit(2)
