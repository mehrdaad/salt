'''
Install Python packages with pip to either the system or a virtualenv
'''

# Import python libs
import os
import re
import logging
import shutil

# Import salt libs
import salt.utils
from salt._compat import string_types
from salt.exceptions import CommandExecutionError, CommandNotFoundError

# It would be cool if we could use __virtual__() in this module, though, since
# pip can be installed on a virtualenv anywhere on the filesystem, there's no
# definite way to tell if pip is installed on not.

logger = logging.getLogger(__name__)  # pylint: disable=C0103

# Don't shadow built-in's.
__func_alias__ = {
    'list_': 'list'
}

VALID_PROTOS = ['http', 'https', 'ftp']


def _get_pip_bin(bin_env):
    '''
    Return the pip command to call, either from a virtualenv, an argument
    passed in, or from the global modules options
    '''
    if not bin_env:
        which_result = __salt__['cmd.which_bin'](['pip2', 'pip', 'pip-python'])
        if which_result is None:
            raise CommandNotFoundError('Could not find a `pip` binary')
        return which_result

    # try to get pip bin from env
    if os.path.isdir(bin_env):
        if salt.utils.is_windows():
            pip_bin = os.path.join(bin_env, 'Scripts', 'pip.exe')
        else:
            pip_bin = os.path.join(bin_env, 'bin', 'pip')
        if os.path.isfile(pip_bin):
            return pip_bin
        raise CommandNotFoundError('Could not find a `pip` binary')

    return bin_env


def _get_cached_requirements(requirements):
    '''Get the location of a cached requirements file; caching if necessary.'''
    cached_requirements = __salt__['cp.is_cached'](
        requirements, __env__
    )
    if not cached_requirements:
        # It's not cached, let's cache it.
        cached_requirements = __salt__['cp.cache_file'](
            requirements, __env__
        )
    # Check if the master version has changed.
    if __salt__['cp.hash_file'](requirements, __env__) != \
            __salt__['cp.hash_file'](cached_requirements, __env__):
        cached_requirements = __salt__['cp.cache_file'](
            requirements, __env__
        )

    return cached_requirements


def _get_env_activate(bin_env):
    if not bin_env:
        raise CommandNotFoundError('Could not find a `activate` binary')

    if os.path.isdir(bin_env):
        if salt.utils.is_windows():
            activate_bin = os.path.join(bin_env, 'Scripts', 'activate.bat')
        else:
            activate_bin = os.path.join(bin_env, 'bin', 'activate')
        if os.path.isfile(activate_bin):
            return activate_bin
    raise CommandNotFoundError('Could not find a `activate` binary')


def install(pkgs=None,
            requirements=None,
            env=None,
            bin_env=None,
            log=None,
            proxy=None,
            timeout=None,
            editable=None,
            find_links=None,
            index_url=None,
            extra_index_url=None,
            no_index=False,
            mirrors=None,
            build=None,
            target=None,
            download=None,
            download_cache=None,
            source=None,
            upgrade=False,
            force_reinstall=False,
            ignore_installed=False,
            exists_action=None,
            no_deps=False,
            no_install=False,
            no_download=False,
            install_options=None,
            runas=None,
            no_chown=False,
            cwd=None,
            activate=False,
            __env__='base'):
    '''
    Install packages with pip

    Install packages individually or from a pip requirements file. Install
    packages globally or to a virtualenv.

    pkgs
        comma separated list of packages to install
    requirements
        path to requirements
    bin_env
        path to pip bin or path to virtualenv. If doing a system install,
        and want to use a specific pip bin (pip-2.7, pip-2.6, etc..) just
        specify the pip bin you want.
        If installing into a virtualenv, just use the path to the virtualenv
        (/home/code/path/to/virtualenv/)
    env
        deprecated, use bin_env now
    log
        Log file where a complete (maximum verbosity) record will be kept
    proxy
        Specify a proxy in the form
        user:passwd@proxy.server:port. Note that the
        user:password@ is optional and required only if you
        are behind an authenticated proxy.  If you provide
        user@proxy.server:port then you will be prompted for a
        password.
    timeout
        Set the socket timeout (default 15 seconds)
    editable
        install something editable (i.e.
        git+https://github.com/worldcompany/djangoembed.git#egg=djangoembed)
    find_links
        URL to look for packages at
    index_url
        Base URL of Python Package Index
    extra_index_url
        Extra URLs of package indexes to use in addition to ``index_url``
    no_index
        Ignore package index
    mirrors
        Specific mirror URL(s) to query (automatically adds --use-mirrors)
    build
        Unpack packages into ``build`` dir
    target
        Install packages into ``target`` dir
    download
        Download packages into ``download`` instead of installing them
    download_cache
        Cache downloaded packages in ``download_cache`` dir
    source
        Check out ``editable`` packages into ``source`` dir
    upgrade
        Upgrade all packages to the newest available version
    force_reinstall
        When upgrading, reinstall all packages even if they are already
        up-to-date.
    ignore_installed
        Ignore the installed packages (reinstalling instead)
    exists_action
        Default action when a path already exists: (s)witch, (i)gnore, (w)wipe, (b)ackup
    no_deps
        Ignore package dependencies
    no_install
        Download and unpack all packages, but don't actually install them
    no_download
        Don't download any packages, just install the ones
        already downloaded (completes an install run with
        --no-install)
    install_options
        Extra arguments to be supplied to the setup.py install
        command (use like --install-option="--install-
        scripts=/usr/local/bin").  Use multiple --install-
        option options to pass multiple options to setup.py
        install.  If you are using an option with a directory
        path, be sure to use absolute path.
    runas
        User to run pip as
    no_chown
        When runas is given, do not attempt to copy and chown
        a requirements file
    cwd
        Current working directory to run pip from
    activate
        Activates the virtual environment, if given via bin_env,
        before running install.


    CLI Example::

        salt '*' pip.install <package name>,<package2 name>

        salt '*' pip.install requirements=/path/to/requirements.txt

        salt '*' pip.install <package name> bin_env=/path/to/virtualenv

        salt '*' pip.install <package name> bin_env=/path/to/pip_bin

    Complicated CLI example::

        salt '*' pip.install markdown,django editable=git+https://github.com/worldcompany/djangoembed.git#egg=djangoembed upgrade=True no_deps=True

    '''
    # Switching from using `pip_bin` and `env` to just `bin_env`
    # cause using an env and a pip bin that's not in the env could
    # be problematic.
    # Still using the `env` variable, for backwards compatibility's sake
    # but going fwd you should specify either a pip bin or an env with
    # the `bin_env` argument and we'll take care of the rest.
    if env and not bin_env:
        bin_env = env

    cmd = [_get_pip_bin(bin_env), 'install']

    if activate and bin_env:
        if not salt.utils.is_windows():
            cmd = ['.', _get_env_activate(bin_env), '&&'] + cmd

    if pkgs:
        if isinstance(pkgs, basestring):
            if ',' in pkgs:
                pkgs = [p.strip() for p in pkgs.split(',')]
            else:
                pkgs = [pkgs]

        # It's possible we replaced version-range commas with semicolons so
        # they would survive the previous line (in the pip.installed state).
        # Put the commas back in
        cmd.extend(
            [p.replace(';', ',') for p in pkgs]
        )

    if editable:
        egg_match = re.compile(r'(?:#|#.*?&)egg=([^&]*)')
        if isinstance(editable, basestring):
            if ',' in editable:
                editable = [e.strip() for e in editable.split(',')]
            else:
                editable = [editable]

        for entry in editable:
            # Is the editable local?
            if not entry.startswith(('file://', '/')):
                match = egg_match.search(entry)

                if not match or not match.group(1):
                    # Missing #egg=theEggName
                    raise Exception('You must specify an egg for this editable')
            cmd.append('--editable={0}'.format(entry))

    treq = None
    if requirements:
        if requirements.startswith('salt://'):
            cached_requirements = _get_cached_requirements(requirements)
            if not cached_requirements:
                return {
                    'result': False,
                    'comment': (
                        'pip requirements file {0!r} not found'.format(
                            requirements
                        )
                    )
                }
            requirements = cached_requirements

        if runas and not no_chown:
            # Need to make a temporary copy since the runas user will, most
            # likely, not have the right permissions to read the file
            treq = salt.utils.mkstemp()
            shutil.copyfile(requirements, treq)
            logger.debug(
                'Changing ownership of requirements file {0!r} to '
                'user {1!r}'.format(treq, runas)
            )
            __salt__['file.chown'](treq, runas, None)

        cmd.append('--requirement={0!r}'.format(treq or requirements))

    if log:
        try:
            # TODO make this check if writeable
            os.path.exists(log)
        except IOError:
            raise IOError('{0!r} is not writeable'.format(log))

        cmd.append('--log={0}'.format(log))

    if proxy:
        cmd.append('--proxy={0}'.format(proxy))

    if timeout:
        try:
            int(timeout)
        except ValueError:
            raise ValueError(
                '{0!r} is not a valid integer base 10.'.format(timeout)
            )
        cmd.append('--timeout={0}'.format(timeout))

    if find_links:
        if not salt.utils.valid_url(find_links, VALID_PROTOS):
            raise Exception('{0!r} must be a valid URL'.format(find_links))
        cmd.append('--find-links={0}'.format(find_links))


    if no_index and (index_url or extra_index_url):
        raise Exception(
            '\'no_index\' and (\'index_url\' or \'extra_index_url\') are '
            'mutually exclusive.'
        )

    if index_url:
        if not salt.utils.valid_url(index_url, VALID_PROTOS):
            raise Exception('{0!r} must be a valid URL'.format(index_url))
        cmd.append('--index-url={0!r}'.format(index_url))

    if extra_index_url:
        if not salt.utils.valid_url(extra_index_url, VALID_PROTOS):
            raise Exception(
                '{0!r} must be a valid URL'.format(extra_index_url)
            )
        cmd.append('--extra-index-url={0!r} '.format(extra_index_url))

    if no_index:
        cmd.append('--no-index')

    if mirrors:
        if isinstance(mirrors, basestring):
            if ',' in mirrors:
                mirrors = [m.strip() for m in mirrors.split(',')]
            else:
                mirrors = [mirrors]

        cmd.append('--use-mirrors')
        for mirror in mirrors:
            if not mirror.startswith('http://'):
                raise Exception('{0!r} must be a valid URL'.format(mirror))
            cmd.append('--mirrors={0}'.format(mirror))

    if build:
        cmd.append('--build={0}'.format(build=build))

    if target:
        cmd.append('--target={0}'.format(target))

    if download:
        cmd.append('--download={0}'.format(download))

    if download_cache:
        cmd.append('--download-cache={0}'.format(download_cache))

    if source:
        cmd.append('--source={0}'.format(source))

    if upgrade:
        cmd.append('--upgrade')

    if force_reinstall:
        cmd.append('--force-reinstall')

    if ignore_installed:
        cmd.append('--ignore-installed')

    if exists_action:
        cmd.append('--exists-action={0}'.format(exists_action))

    if no_deps:
        cmd.append('--no-deps')

    if no_install:
        cmd.append('--no-install')

    if no_download:
        cmd.append('--no-download')

    if install_options:
        if isinstance(install_options, string_types):
            install_options = [install_options]

        for opt in install_options:
            cmd.append('--install-option={0}'.format(opt))

    try:
        return __salt__['cmd.run_all'](' '.join(cmd), runas=runas, cwd=cwd)
    finally:
        if treq is not None:
            try:
                os.remove(treq)
            except Exception:
                pass


def uninstall(pkgs=None,
              requirements=None,
              bin_env=None,
              log=None,
              proxy=None,
              timeout=None,
              runas=None,
              cwd=None,
              __env__='base'):
    '''
    Uninstall packages with pip

    Uninstall packages individually or from a pip requirements file. Uninstall
    packages globally or from a virtualenv.

    pkgs
        comma separated list of packages to install
    requirements
        path to requirements
    bin_env
        path to pip bin or path to virtualenv. If doing an uninstall from
        the system python and want to use a specific pip bin (pip-2.7,
        pip-2.6, etc..) just specify the pip bin you want.
        If uninstalling from a virtualenv, just use the path to the virtualenv
        (/home/code/path/to/virtualenv/)
    log
        Log file where a complete (maximum verbosity) record will be kept
    proxy
        Specify a proxy in the form
        user:passwd@proxy.server:port. Note that the
        user:password@ is optional and required only if you
        are behind an authenticated proxy.  If you provide
        user@proxy.server:port then you will be prompted for a
        password.
    timeout
        Set the socket timeout (default 15 seconds)
    runas
        User to run pip as
    cwd
        Current working directory to run pip from

    CLI Example::

        salt '*' pip.uninstall <package name>,<package2 name>

        salt '*' pip.uninstall requirements=/path/to/requirements.txt

        salt '*' pip.uninstall <package name> bin_env=/path/to/virtualenv

        salt '*' pip.uninstall <package name> bin_env=/path/to/pip_bin

    '''
    cmd = '{0} uninstall -y '.format(_get_pip_bin(bin_env))

    if pkgs:
        pkg = pkgs.replace(',', ' ')
        cmd = '{cmd} {pkg} '.format(
            cmd=cmd, pkg=pkg)

    treq = None
    if requirements:
        if requirements.startswith('salt://'):
            req = __salt__['cp.cache_file'](requirements, __env__)
            treq = salt.utils.mkstemp()
            shutil.copyfile(req, treq)
        cmd = '{cmd} --requirements {requirements!r} '.format(
            cmd=cmd, requirements=treq or requirements)

    if log:
        try:
            # TODO make this check if writeable
            os.path.exists(log)
        except IOError:
            raise IOError('{0!r} is not writeable'.format(log))
        cmd = '{cmd} --{log} '.format(
            cmd=cmd, log=log)

    if proxy:
        cmd = '{cmd} --proxy={proxy} '.format(
            cmd=cmd, proxy=proxy)

    if timeout:
        try:
            int(timeout)
        except ValueError:
            raise ValueError(
                '\'{0}\' is not a valid integer base 10.'.format(timeout)
            )
        cmd = '{cmd} --timeout={timeout} '.format(
            cmd=cmd, timeout=timeout)

    result = __salt__['cmd.run_all'](cmd, runas=runas, cwd=cwd)

    if treq and requirements.startswith('salt://'):
        try:
            os.remove(treq)
        except Exception:
            pass

    return result


def freeze(bin_env=None,
           runas=None,
           cwd=None):
    '''
    Return a list of installed packages either globally or in the specified
    virtualenv

    bin_env
        path to pip bin or path to virtualenv. If doing an uninstall from
        the system python and want to use a specific pip bin (pip-2.7,
        pip-2.6, etc..) just specify the pip bin you want.
        If uninstalling from a virtualenv, just use the path to the virtualenv
        (/home/code/path/to/virtualenv/)
    runas
        User to run pip as
    cwd
        Current working directory to run pip from

    CLI Example::

        salt '*' pip.freeze /home/code/path/to/virtualenv/
    '''

    cmd = '{0} freeze'.format(_get_pip_bin(bin_env))

    result = __salt__['cmd.run_all'](cmd, runas=runas, cwd=cwd)

    if result['retcode'] > 0:
        raise CommandExecutionError(result['stderr'])

    return result['stdout'].splitlines()


def list_(prefix='',
         bin_env=None,
         runas=None,
         cwd=None):
    '''
    Filter list of installed apps from ``freeze`` and check to see if
    ``prefix`` exists in the list of packages installed.

    CLI Example::

        salt '*' pip.list salt
    '''
    packages = {}

    cmd = '{0} freeze'.format(_get_pip_bin(bin_env))

    result = __salt__['cmd.run_all'](cmd, runas=runas, cwd=cwd)
    if result['retcode'] > 0:
        raise CommandExecutionError(result['stderr'])

    for line in result['stdout'].splitlines():
        if line.startswith('-e'):
            line = line.split('-e ')[1]
            version, name = line.split('#egg=')
        elif len(line.split('==')) >= 2:
            name = line.split('==')[0]
            version = line.split('==')[1]

        if prefix:
            if name.lower().startswith(prefix.lower()):
                packages[name] = version
        else:
            packages[name] = version
    return packages
