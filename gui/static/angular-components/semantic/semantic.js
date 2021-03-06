'use strict';

goog.provide('grrUi.semantic.module');

goog.require('grrUi.core.module');
goog.require('grrUi.semantic.clientUrnDirective.ClientUrnDirective');
goog.require('grrUi.semantic.macAddressDirective.MacAddressDirective');
goog.require('grrUi.semantic.semanticProtoDirective.SemanticProtoDirective');
goog.require('grrUi.semantic.semanticValueDirective.SemanticValueDirective');
goog.require('grrUi.semantic.timestampDirective.TimestampDirective');


/**
 * Module with directives that render semantic values (i.e. RDFValues) fetched
 * from the server.
 */
grrUi.semantic.module = angular.module('grrUi.semantic',
                                       [grrUi.core.module.name,
                                        'ui.bootstrap']);


grrUi.semantic.module.directive(
    grrUi.semantic.clientUrnDirective.ClientUrnDirective.directive_name,
    grrUi.semantic.clientUrnDirective.ClientUrnDirective);
grrUi.semantic.module.directive(
    grrUi.semantic.macAddressDirective.MacAddressDirective.directive_name,
    grrUi.semantic.macAddressDirective.MacAddressDirective);
grrUi.semantic.module.directive(
    grrUi.semantic.semanticProtoDirective.SemanticProtoDirective.directive_name,
    grrUi.semantic.semanticProtoDirective.SemanticProtoDirective);
grrUi.semantic.module.directive(
    grrUi.semantic.semanticValueDirective.SemanticValueDirective.directive_name,
    grrUi.semantic.semanticValueDirective.SemanticValueDirective);
grrUi.semantic.module.directive(
    grrUi.semantic.timestampDirective.TimestampDirective.directive_name,
    grrUi.semantic.timestampDirective.TimestampDirective);
