from daemon import Daemon
import os
import gearman
from vagrant import Vagrant
import logging
import sys
import sh
import re
import json

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('vagrant-worker.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

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
                gm_worker.work()


def ip(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Getting IP from vagrant machine')
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        ips = sh.vagrant('ssh', '-c', 'ip addr list eth1')
        search = re.match(r'.* inet (.*)/24 brd', ips.stdout.replace('\n', ''))
        if search:
            ip = search.group(1)

    except:
        logger.error('Unable to connect to machine to it\'s IP :: {}'
                     .format(path))

    os.chdir(old_path)
    return ip


def run(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    eth = _get_eth(gearman_job)
    environment = _get_environment(gearman_job)
    logger.debug('Bring up {} with eth {} and environment set to {}'
                 .format(path, eth, environment))

    vagrant = Vagrant(path)
    try:
        os.environ['ETH'] = eth
        os.environ['ENVIRONMENT'] = environment
        vagrant.up()
    except:
        logger.error('Failed to bring up machine {}'.format(path),
                     exc_info=True)
    logger.debug('Done bring up {}'.format(path))

    return _get_status(vagrant)


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
    return _get_status(vagrant)


def status(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.debug('Asking Status for {}'.format(path))

    vagrant = Vagrant(path)
    try:
        status = _get_status(vagrant)
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    logger.debug('Status : {} :: {}'.format(status, path))
    return _get_status(vagrant)


def _get_path(gearman_job):
    data = json.loads(gearman_job.data)
    return data['path']


def _get_eth(gearman_job):
    data = json.loads(gearman_job.data)
    return data['eth']


def _get_environment(gearman_job):
    data = json.loads(gearman_job.data)
    return data['environment']


def _get_status(vagrant):
    statuses = vagrant.status()
    return json.dumps(statuses)


if __name__ == '__main__':
    #app = App('/var/run/vagrant-worker.pid'.format(os.getpid()))
    app = App('pids/vagrant-worker-{}.pid'.format(os.getpid()))
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
