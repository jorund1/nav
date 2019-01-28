==============================================
Installing Graphite for use with NAV on Debian
==============================================

This is a short how-to guide for installing and configuring a simple Graphite
installation, dedicated to NAV, on a **Debian 9 (Stretch)** server.

.. warning:: **Do not start NAV** until you have properly configured your
             carbon-cache's storage schemas with NAV's provided storage schema
             config, or you *will* have issues with :doc:`blank areas in your
             graphs </faq/graph_gaps>`, which you will need to resolve
             manually after-the-fact.


Getting Graphite
================

A full Graphite setup consists of the *Carbon* backend server, which receives
metrics over TCP or UDP, and a *Graphite web frontend*, which enables browsing
and retrievial/rendering of the stored metrics. NAV will collect metrics and
send to the former, while utilizing the latter to retrieve metrics and render
graphs.

Assuming you will be running Graphite on the same Debian server as you are
running NAV, all you need to do to install Graphite is::

  apt-get install -t stretch-backports/graphite-carbon graphite-web


.. note:: For some strange reason, Twisted may be installed in two places at
          this point, causing ``carbon-cache`` startup to fail. If you see an
          error that looks like this:: error::

            Job for carbon-cache.service failed because the control process exited with error code.
            See "systemctl status carbon-cache.service" and "journalctl -xe" for details.
            invoke-rc.d: initscript carbon-cache, action "start" failed.
            ● carbon-cache.service - Graphite Carbon Cache
               Loaded: loaded (/lib/systemd/system/carbon-cache.service; enabled; vendor preset: enabled)
               Active: failed (Result: exit-code) since Mon 2019-01-28 10:55:45 CET; 13ms ago
              Process: 3142 ExecStart=/usr/bin/carbon-cache --config=/etc/carbon/carbon.conf --pidfile=/var/run/carbon-cache.pid --logdir=/var/log/carbon/ start (code=exited, status=1/FAILURE)

            Jan 28 10:55:45 myserver carbon-cache[3142]:     config.parseOptions(twistd_options)
            Jan 28 10:55:45 myserver carbon-cache[3142]:   File "/usr/local/lib/python2.7/dist-packages/twisted/application/app.py", line 624,…seOptions
            Jan 28 10:55:45 myserver carbon-cache[3142]:     usage.Options.parseOptions(self, options)
            Jan 28 10:55:45 myserver carbon-cache[3142]:   File "/usr/local/lib/python2.7/dist-packages/twisted/python/usage.py", line 270, in…seOptions
            Jan 28 10:55:45 myserver carbon-cache[3142]:     raise UsageError("Unknown command: %s" % sub)
            Jan 28 10:55:45 myserver carbon-cache[3142]: twisted.python.usage.UsageError: Unknown command: carbon-cache
            Jan 28 10:55:45 myserver systemd[1]: carbon-cache.service: Control process exited, code=exited status=1
            Jan 28 10:55:45 myserver systemd[1]: Failed to start Graphite Carbon Cache.
            Jan 28 10:55:45 myserver systemd[1]: carbon-cache.service: Unit entered failed state.
            Jan 28 10:55:45 myserver systemd[1]: carbon-cache.service: Failed with result 'exit-code'.
            Hint: Some lines were ellipsized, use -l to show in full.

          ...you may need to execute ``rm -rf
          /usr/local/lib/python2.7/dist-packages/twisted/`` followed by a
          ``dpkg --configure -a`` to rectify the situation.


Configuring Carbon
==================

Carbon, the metric-receiving backend of Graphite, must be configured before it
can be used with NAV. We will only be covering the simple case of using a
single *carbon-cache* process. Most of this information is adapted from the
:ref:`integrating-graphite-with-nav` section of the generic installation
documentation.

Edit :file:`/etc/carbon/carbon.conf` to ensure these options are set in the
``[cache]`` section:

.. code-block:: ini

   MAX_CREATES_PER_MINUTE = inf
   ENABLE_UDP_LISTENER = True

The first line ensures that Carbon will not delay creating Whisper backend
files for the metrics NAV sends it. The default setting is a maximum of 50
creates per minute (the setting exists to limit I/O strain on huge setups),
which means that when bootstrapping a NAV installation, hours to days can pass
before all its metrics are being actually stored in Graphite.

The second line ensures that Carbon accepts metrics on a UDP socket, which is
required by NAV.

Carbon also needs to know the resolution at which to store your time-series
data, for how long to store it, and how to roll up data from high resolution
data archives to lower resolution archives. These are the storage schemas and
aggregation methods. NAV provides its own config examples for this; on a
Graphite backend *dedicated to NAV*, you can simply symlink these config files
from NAV::

  cd /etc/carbon/
  mv storage-schemas.conf storage-schemas.conf.bak
  mv storage-aggregation.conf storage-aggregation.conf.bak
  ln -s /etc/nav/graphite/*.conf /etc/carbon/

Finally, restart the ``carbon-cache`` daemon::

  systemctl restart carbon-cache

Configuring the Graphite web interface
======================================

To enable the web interface, you need to do two things:

- Configure and create the database it will use for storing graph definitions.
- Configure Apache to serve the web interface.

Creating the graphite database
------------------------------

Graphite will by default use a SQLite database, but this is not recommended in
a production setting, as it will cause issues with multiple simultaneous
users. You already have a PostgreSQL installation because of NAV, so we
recommend using this.

Make a ``graphite`` PostgreSQL user and give it a password (make note of the
password), then create a database owned by that user::

  sudo -u postgres createuser --pwprompt --no-createrole --no-superuser --no-createdb --login graphite
  sudo -u postgres createdb --owner=graphite graphite

The Graphite web app's configuration file is located in
:file:`/etc/graphite/local_settings.py`. There are mainly three settings you
will need to adjust: ``SECRET_KEY``, ``TIME_ZONE`` and ``DATABASES``. The
``SECRET_KEY`` is used for cryptographic purposes when working with cookies and
session data (just as the ``SECRET_KEY`` setting from :file:`nav.conf`). It
should be a random string of characters; we can suggest using the
``makepasswd`` command to generate such a string:

.. code-block:: console

  $ makepasswd --chars 51
  iLNScMiUpNy5hditWAp9e2dyHGTFoX44UKsbhj91f9xL4fdJSDY

Then edit :file:`/etc/graphite/local_settings.py` (do not, under any
circumstances, re-use the actual example value of ``SECRET_KEY`` here!) and
make to set these three settings:

.. code-block:: python

   SECRET_KEY = 'iLNScMiUpNy5hditWAp9e2dyHGTFoX44UKsbhj91f9xL4fdJSDY'
   TIME_ZONE = 'Europe/Oslo' # This should correspond to your actual timezone, also as in nav.conf
   DATABASES = {
       'default': {
           'NAME': 'graphite',
           'ENGINE': 'django.db.backends.postgresql_psycopg2',
           'USER': 'graphite',
           'PASSWORD': 'the password you made note of above',
           'HOST': 'localhost',
           'PORT': '5432'
       }
   }


Now make ``graphite-web`` initialize its database schema::

  graphite-manage migrate auth --noinput
  graphite-manage migrate --noinput

Configure Apache to serve the Graphite web app
----------------------------------------------

In principle, you can use any web server that supports the WSGI interface, but
you already have Apache because of NAV, so lets use that. Graphite-web will
need its own virtualhost, so let's add a new site config for Apache in
:file:`/etc/apache2/sites-available/graphite-web.conf` (this example is
inspired by the one supplied by the ``graphite-web`` package in
:file:`/usr/share/graphite-web/apache2-graphite.conf`):

.. code-block:: apacheconf

   Listen 8000
   <VirtualHost *:8000>

           WSGIDaemonProcess _graphite processes=1 threads=1 display-name='%{GROUP}' inactivity-timeout=120 user=_graphite group=_graphite
           WSGIProcessGroup _graphite
           WSGIImportScript /usr/share/graphite-web/graphite.wsgi process-group=_graphite application-group=%{GLOBAL}
           WSGIScriptAlias / /usr/share/graphite-web/graphite.wsgi

           Alias /content/ /usr/share/graphite-web/static/
           <Location "/content/">
                   SetHandler None
           </Location>

           ErrorLog ${APACHE_LOG_DIR}/graphite-web_error.log

           # Possible values include: debug, info, notice, warn, error, crit,
           # alert, emerg.
           LogLevel warn

           CustomLog ${APACHE_LOG_DIR}/graphite-web_access.log combined

   </VirtualHost>


This defines a virtual host that will serve the Graphite web app on port
**8000**. Adding SSL encryption is left as an excercise for the reader.

.. warning:: All graphite statistics will become browseable for anyone who can
             access your server on port 8000. You will probably want to
             restrict access to this port, either by using iptables or ACLs in
             your routers. Or, if you do not care about browsing the web app
             yourself, change the ``Listen`` statement into ``Listen
             127.0.0.1:8000``, so that only the NAV installation on
             ``localhost`` will be able to access it.

Now, enable the new site on port 8000::

  a2ensite graphite-web
  systemctl restart apache2


Congratulations, you should now be ready to start NAV!