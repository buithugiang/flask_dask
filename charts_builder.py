# -*- coding: utf-8 -*-

"""
flask_jsondash.charts_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The chart blueprint that houses all functionality.

:copyright: (c) 2016 by Chris Tabor.
:license: MIT, see LICENSE for more details.
"""

import json
import os
import uuid
import pdb
from collections import namedtuple
from datetime import datetime as dt

import jinja2
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from werkzeug import secure_filename

import static, templates
import db
from settings import CHARTS_CONFIG

template_dir = os.path.dirname(templates.__file__)
static_dir = os.path.dirname(static.__file__)

Paginator = namedtuple('Paginator',
                       'count per_page curr_page num_pages limit skip')

charts = Blueprint(
    'jsondash',
    __name__,
    template_folder=template_dir,
    static_url_path=static_dir,
    static_folder=static_dir,
)
default_config = dict(
    JSONDASH_FILTERUSERS=False,
    JSONDASH_GLOBALDASH=False,
    JSONDASH_GLOBAL_USER='global',
    JSONDASH_PERPAGE=25,
)
adapter = db.get_db_handler()




@charts.context_processor
def ctx():
    """Inject any context needed for this blueprint."""
    filter_user = setting('JSONDASH_FILTERUSERS')
    static = setting('JSONDASH').get('static')
    # Rewrite the static config paths to be local if the overrides are set.
    config = (CHARTS_CONFIG if not static
              else local_static(CHARTS_CONFIG, static))
    return dict(
        static_config=static,
        charts_config=config,
        page_title='dashboards',
        demo_mode=request.args.get('jsondash_demo_mode', False),
        global_dashuser=setting('JSONDASH_GLOBAL_USER'),
        global_dashboards=setting('JSONDASH_GLOBALDASH'),
        username=metadata(key='username') if filter_user else None,
        filter_dashboards=filter_user,
    )


@jinja2.contextfilter
@charts.app_template_filter('get_dims')
def get_dims(_, config):
    """Extract the dimensions from config data. This allows
    for overrides for edge-cases to live in one place.
    """
    if not all(['width' in config, 'height' in config]):
        raise ValueError('Invalid config!')
    if config.get('type') == 'youtube':
        # We get the dimensions for the widget from YouTube instead,
        # which handles aspect ratios, etc... and is likely what the user
        # wanted to specify since they will be entering in embed code from
        # Youtube directly.
        embed = config['dataSource'].split(' ')
        padding_w = 20
        padding_h = 60
        w = int(embed[1].replace('width=', '').replace('"', ''))
        h = int(embed[2].replace('height=', '').replace('"', ''))
        return dict(width=w + padding_w, height=h + padding_h)
    return dict(width=config['width'], height=config['height'])


@jinja2.contextfilter
@charts.app_template_filter('jsonstring')
def jsonstring(ctx, data):
    """Format view json module data for template use.

    It's automatically converted to unicode key/value pairs,
    which is undesirable for the template.
    """
    if 'date' in data:
        data['date'] = str(data['date'])
    return json.dumps(data)


@charts.route('/charts', methods=['GET'])
@charts.route('/charts/', methods=['GET'])
def dashboard():
    """Load all views."""
    opts = dict()
    views = []
    if setting('JSONDASH_FILTERUSERS'):
        opts.update(filter=dict(created_by=metadata(key='username')))
        views = list(adapter.read(**opts))
        if setting('JSONDASH_GLOBALDASH'):
            opts.update(
                filter=dict(created_by=setting('JSONDASH_GLOBAL_USER')))
            views += list(adapter.read(**opts))
    else:
        views = list(adapter.read(**opts))
    if views:
        page = request.args.get('page')
        per_page = request.args.get('per_page')
        paginator_args = dict(count=len(views))
        if per_page is not None:
            paginator_args.update(per_page=int(per_page))
        if page is not None:
            paginator_args.update(page=int(page))
        pagination = paginator(**paginator_args)
        opts.update(limit=pagination.limit, skip=pagination.skip)
    else:
        pagination = None
    kwargs = dict(
        views=views,
        view=None,
        paginator=pagination,
        total_modules=sum([
            len(view.get('modules', [])) for view in views
            if isinstance(view, dict)
        ]),
    )
    return render_template('partials/edit-data-modal.html', **kwargs)

@charts.route('/charts/uploader', methods = ['POST'])
def upload_file():
   if request.method == 'POST':
      f = request.files['file']
      f.save(secure_filename(f.filename))
      return secure_filename(f.filename)

def paginator(page=0, per_page=None, count=None):
    """Get pagination calculations in a compact format."""
    if count is None:
        count = adapter.count()
    if page is None:
        page = 0
    default_per_page = setting('JSONDASH_PERPAGE')
    # Allow query parameter overrides.
    per_page = per_page if per_page is not None else default_per_page
    per_page = per_page if per_page > 2 else 2  # Prevent division errors etc
    curr_page = page - 1 if page > 0 else 0
    num_pages = count // per_page
    rem = count % per_page
    extra_pages = 2 if rem else 1
    pages = list(range(1, num_pages + extra_pages))
    return Paginator(
        limit=per_page,
        per_page=per_page,
        curr_page=curr_page,
        skip=curr_page * per_page,
        num_pages=pages,
        count=count,
    )

def local_static(chart_config, static_config):
    """Convert remote cdn urls to local urls, based on user provided paths.
    The filename must be identical to the one specified in the
    `settings.py` configuration.
    So, for example:
    '//cdnjs.cloudflare.com/foo/bar/foo.js'
    becomes
    '/static/js/vendor/foo.js'
    """
    js_path = static_config.get('js_path')
    css_path = static_config.get('css_path')
    for family, config in chart_config.items():
        if config['js_url']:
            for i, url in enumerate(config['js_url']):
                url = '{}{}'.format(js_path, url.split('/')[-1])
                config['js_url'][i] = url_for('static', filename=url)
        if config['css_url']:
            for i, url in enumerate(config['css_url']):
                url = '{}{}'.format(css_path, url.split('/')[-1])
                config['css_url'][i] = url_for('static', filename=url)
    return chart_config

@charts.route('/charts/<path:filename>')
def _static(filename):
    """Send static files directly for this blueprint."""
    return send_from_directory(directory=current_app.root_path, filename=filename)

def setting(name, default=None):
    """A simplified getter for namespaced flask config values."""
    if default is None:
        default = default_config.get(name)
    return current_app.config.get(name, default)
