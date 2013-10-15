#!/usr/bin/env python
"""Classes for exporting data from AFF4 to the rest of the world.

Exporters defined here convert various complex RDFValues to simple RDFValues
(without repeated fields, without recursive field definitions) that can
easily be written to a relational database or just to a set of files.
"""

import hashlib
import stat
import time

import logging


from grr.lib import aff4
from grr.lib import rdfvalue
from grr.lib import registry
from grr.lib import threadpool
from grr.lib import utils
from grr.proto import export_pb2


class Error(Exception):
  """Errors generated by export converters."""


class NoConverterFound(Error):
  """Raised when no converter is found for particular value."""


class ExportOptions(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportOptions


class ExportedMetadata(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedMetadata


class ExportedClient(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedClient


class ExportedFile(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedFile


class ExportedRegistryKey(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedRegistryKey


class ExportedProcess(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedProcess


class ExportedNetworkConnection(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedNetworkConnection


class ExportedOpenFile(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedOpenFile


class ExportedVolatilityHandle(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedVolatilityHandle


class ExportedVolatilityMutant(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedVolatilityMutant


class ExportedNetworkInterface(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedNetworkInterface


class ExportedFileStoreHash(rdfvalue.RDFProtoStruct):
  protobuf = export_pb2.ExportedFileStoreHash


class ExportConverter(object):
  """Base ExportConverter class."""

  __metaclass__ = registry.MetaclassRegistry

  # Type of values that this converter accepts.
  input_rdf_type = None

  def __init__(self, options=None):
    """Constructor.

    Args:
      options: ExportOptions value, which contains settings that may or
               or may not affect this converter's behavior.
    """
    super(ExportConverter, self).__init__()
    self.options = options or rdfvalue.ExportOptions()

  def Convert(self, metadata, value, token=None):
    """Converts given RDFValue to other RDFValues.

    Args:
      metadata: ExporteMetadata to be used for conversion.
      value: RDFValue to be converted.
      token: Security token.

    Yields:
      Resulting RDFValues. Empty list is a valid result and means that
      conversion wasn't possible. Resulting RDFValues may be of different
      types.
    """
    raise NotImplementedError()

  def BatchConvert(self, metadata_value_pairs, token=None):
    """Converts a batch of RDFValues at once.

    This is a default non-optimized dumb implementation. Subclasses are
    supposed to have their own optimized implementations.

    Args:
      metadata_value_pairs: a list or a generator of tuples (metadata, value),
                            where metadata is ExportedMetadata to be used for
                            conversion and value is an RDFValue to be converted.
      token: Security token:

    Yields:
      Resulting RDFValues. Empty list is a valid result and means that
      conversion wasn't possible. Resulting RDFValues may be of different
      types.
    """
    for metadata, value in metadata_value_pairs:
      for result in self.Convert(metadata, value, token):
        yield result

  @staticmethod
  def GetConvertersByValue(value):
    """Returns all converters that take given value as an input value."""
    return [cls for cls in ExportConverter.classes.itervalues()
            if cls.input_rdf_type == value.__class__.__name__]


class StatEntryToExportedFileConverter(ExportConverter):
  """Converts StatEntry to ExportedFile."""

  input_rdf_type = "StatEntry"

  MAX_CONTENT_SIZE = 1024 * 64

  @staticmethod
  def ParseSignedData(signed_data, result):
    """Parses signed certificate data and updates result rdfvalue."""

  @staticmethod
  def ParseFileHash(hash_obj, result):
    """Parses Hash rdfvalue into ExportedFile's fields."""
    if hash_obj.HasField("md5"):
      result.hash_md5 = str(hash_obj.md5)

    if hash_obj.HasField("sha1"):
      result.hash_sha1 = str(hash_obj.sha1)

    if hash_obj.HasField("sha256"):
      result.hash_sha256 = str(hash_obj.sha256)

    if hash_obj.HasField("pecoff_md5"):
      result.pecoff_hash_md5 = str(hash_obj.pecoff_md5)

    if hash_obj.HasField("pecoff_sha1"):
      result.pecoff_hash_sha1 = str(hash_obj.pecoff_sha1)

    if hash_obj.HasField("signed_data"):
      StatEntryToExportedFileConverter.ParseSignedData(
          hash_obj.signed_data[0], result)

  def Convert(self, metadata, stat_entry, token=None):
    """Converts StatEntry to ExportedFile.

    Does nothing if StatEntry corresponds to a registry entry and not to a file.

    Args:
      metadata: ExporteMetadata to be used for conversion.
      stat_entry: StatEntry to be converted.
      token: Security token.

    Returns:
      List or generator with resulting RDFValues. Empty list if StatEntry
      corresponds to a registry entry and not to a file.
    """
    return self.BatchConvert([(metadata, stat_entry)], token=token)

  def BatchConvert(self, metadata_value_pairs, token=None):
    """Converts a batch of StatEntry value to ExportedFile values at once.

    Args:
      metadata_value_pairs: a list or a generator of tuples (metadata, value),
                            where metadata is ExportedMetadata to be used for
                            conversion and value is a StatEntry to be converted.
      token: Security token:

    Yields:
      Resulting ExportedFile values. Empty list is a valid result and means that
      conversion wasn't possible.
    """
    filtered_pairs = []
    for metadata, stat_entry in metadata_value_pairs:
      if not stat_entry.HasField("registry_type"):
        filtered_pairs.append((metadata, stat_entry))

    if self.options.export_files_hashes or self.options.export_files_contents:
      aff4_paths = [stat_entry.aff4path
                    for metadata, stat_entry in metadata_value_pairs]
      fds = aff4.FACTORY.MultiOpen(aff4_paths, mode="r", token=token)
      fds_dict = dict([(fd.urn, fd) for fd in fds])

    for metadata, stat_entry in filtered_pairs:
      result = ExportedFile(metadata=metadata,
                            urn=stat_entry.aff4path,
                            basename=stat_entry.pathspec.Basename(),
                            st_mode=stat_entry.st_mode,
                            st_ino=stat_entry.st_ino,
                            st_dev=stat_entry.st_dev,
                            st_nlink=stat_entry.st_nlink,
                            st_uid=stat_entry.st_uid,
                            st_gid=stat_entry.st_gid,
                            st_size=stat_entry.st_size,
                            st_atime=stat_entry.st_atime,
                            st_mtime=stat_entry.st_mtime,
                            st_ctime=stat_entry.st_ctime,
                            st_blocks=stat_entry.st_blocks,
                            st_blksize=stat_entry.st_blksize,
                            st_rdev=stat_entry.st_rdev,
                            symlink=stat_entry.symlink)

      if self.options.export_files_hashes or self.options.export_files_contents:
        try:
          aff4_object = fds_dict[stat_entry.aff4path]

          if self.options.export_files_hashes:
            hash_obj = aff4_object.Get(aff4_object.Schema.HASH)
            if hash_obj:
              self.ParseFileHash(hash_obj, result)

          if self.options.export_files_contents:
            try:
              result.content = aff4_object.Read(self.MAX_CONTENT_SIZE)
              result.content_sha256 = hashlib.sha256(result.content).hexdigest()
            except (IOError, AttributeError) as e:
              logging.warning("Can't read content of %s: %s",
                              stat_entry.aff4path, e)
        except KeyError:
          pass

      yield result


class StatEntryToExportedRegistryKeyConverter(ExportConverter):
  """Converts StatEntry to ExportedRegistryKey."""

  input_rdf_type = "StatEntry"

  def Convert(self, metadata, stat_entry, token=None):
    """Converts StatEntry to ExportedRegistryKey.

    Does nothing if StatEntry corresponds to a file and nto a registry entry.

    Args:
      metadata: ExporteMetadata to be used for conversion.
      stat_entry: StatEntry to be converted.
      token: Security token.

    Returns:
      List or generator with resulting RDFValues. Empty list if StatEntry
      corresponds to a file and not to a registry entry.
    """
    if not stat_entry.HasField("registry_type"):
      return []

    result = ExportedRegistryKey(metadata=metadata,
                                 urn=stat_entry.aff4path,
                                 last_modified=stat_entry.st_mtime,
                                 type=stat_entry.registry_type)

    try:
      data = str(stat_entry.registry_data.GetValue())
    except UnicodeEncodeError:
      # If we can't represent this as a string...
      # let's just get the byte representation *shrug*
      data = stat.registry_data.GetValue()
        # Get the byte representation of the string
      data = unicode(data).encode("utf-16be")

    result.data = data
    return [result]


class ProcessToExportedProcessConverter(ExportConverter):
  """Converts Process to ExportedProcess."""

  input_rdf_type = "Process"

  def Convert(self, metadata, process, token=None):
    """Converts Process to ExportedProcess."""

    result = ExportedProcess(metadata=metadata,
                             pid=process.pid,
                             ppid=process.ppid,
                             name=process.name,
                             exe=process.exe,
                             cmdline=" ".join(process.cmdline),
                             ctime=process.ctime,
                             real_uid=process.real_uid,
                             effective_uid=process.effective_uid,
                             saved_uid=process.saved_uid,
                             real_gid=process.real_gid,
                             effective_gid=process.effective_gid,
                             saved_gid=process.saved_gid,
                             username=process.username,
                             terminal=process.terminal,
                             status=process.status,
                             nice=process.nice,
                             cwd=process.cwd,
                             num_threads=process.num_threads,
                             user_cpu_time=process.user_cpu_time,
                             system_cpu_time=process.system_cpu_time,
                             cpu_percent=process.cpu_percent,
                             rss_size=process.RSS_size,
                             vms_size=process.VMS_size,
                             memory_percent=process.memory_percent)
    return [result]


class ProcessToExportedNetworkConnectionConverter(ExportConverter):
  """Converts Process to ExportedNetworkConnection."""

  input_rdf_type = "Process"

  def Convert(self, metadata, process, token=None):
    """Converts Process to ExportedNetworkConnection."""

    for conn in process.connections:
      yield ExportedNetworkConnection(metadata=metadata,
                                      family=conn.family,
                                      type=conn.type,
                                      local_address=conn.local_address,
                                      remote_address=conn.remote_address,
                                      state=conn.state,
                                      pid=conn.pid,
                                      ctime=conn.ctime)


class ProcessToExportedOpenFileConverter(ExportConverter):
  """Converts Process to ExportedOpenFile."""

  input_rdf_type = "Process"

  def Convert(self, metadata, process, token=None):
    """Converts Process to ExportedOpenFile."""

    for f in process.open_files:
      yield ExportedOpenFile(metadata=metadata,
                             pid=process.pid,
                             path=f)


class VolatilityResultConverter(ExportConverter):
  """Base class for converting volatility results."""

  __abstract = True  # pylint: disable=g-bad-name

  input_rdf_type = "VolatilityResult"

  mapping = None
  output_rdf_cls = None

  def __init__(self):
    super(VolatilityResultConverter, self).__init__()
    if not self.mapping:
      raise ValueError("Mapping not specified.")

    if not self.output_rdf_cls:
      raise ValueError("output_rdf_cls not specified")

  def Convert(self, metadata, volatility_result, token=None):
    for section in volatility_result.sections:
      # Keep a copy of the headers and their order.
      try:
        headers = tuple(self.mapping[h.name] for h in section.table.headers)
      except KeyError as e:
        logging.warning("Unmapped header: %s", e)
        continue

      if not section.table.rows:
        logging.warning("No rows in the section.")
        continue

      for row in section.table.rows:
        # pylint: disable=not-callable
        out_rdf = self.output_rdf_cls(metadata=metadata)
        # pylint: enable=not-callable

        for attr, value in zip(headers, row.values):
          if isinstance(getattr(out_rdf, attr), (str, unicode)):
            setattr(out_rdf, attr, value.svalue)
          else:
            setattr(out_rdf, attr, value.value)
        yield out_rdf


class VolatilityResultToExportedVolatilityHandleConverter(
    VolatilityResultConverter):
  """Converts VolatilityResult to ExportedVolatilityHandle."""

  mapping = {
      "offset_v": "offset",
      "pid": "pid",
      "handle": "handle",
      "access": "access",
      "obj_type": "type",
      "details": "path",
  }

  output_rdf_cls = rdfvalue.ExportedVolatilityHandle


class VolatilityResultToExportedVolatilityMutantConverter(
    VolatilityResultConverter):
  """Converts VolatilityResult to ExportedVolatilityMutant."""

  mapping = {
      "offset_p": "offset",
      "ptr_count": "ptr_count",
      "hnd_count": "handle_count",
      "mutant_signal": "signal",
      "mutant_thread": "thread",
      "cid": "cid",
      "mutant_name": "name",
  }

  output_rdf_cls = rdfvalue.ExportedVolatilityMutant


class ClientSummaryToExportedNetworkInterfaceConverter(ExportConverter):
  input_rdf_type = "ClientSummary"

  def Convert(self, metadata, client_summary, token=None):
    """Converts ClientSummary to ExportedNetworkInterfaces."""

    for interface in client_summary.interfaces:
      ip4_addresses = []
      ip6_addresses = []
      for addr in interface.addresses:
        if addr.address_type == addr.Family.INET:
          ip4_addresses.append(addr.human_readable_address)
        elif addr.address_type == addr.Family.INET6:
          ip6_addresses.append(addr.human_readable_address)
        else:
          raise ValueError("Invalid address type: %s", addr.address_type)

      result = ExportedNetworkInterface(
          metadata=metadata,
          ifname=interface.ifname,
          ip4_addresses=" ".join(ip4_addresses),
          ip6_addresses=" ".join(ip6_addresses))

      if interface.mac_address:
        result.mac_address = interface.mac_address.human_readable_address

      yield result


class ClientSummaryToExportedClientConverter(ExportConverter):
  input_rdf_type = "ClientSummary"

  def Convert(self, metadata, unused_client_summary, token=None):
    return [ExportedClient(metadata=metadata)]


class RDFURNConverter(ExportConverter):
  """Follows RDFURN and converts its target object into a set of RDFValues.

  If urn points to a RDFValueCollection, RDFURNConverter goes through the
  collection and converts every value there. If urn points to an object
  with "STAT" attribute, it converts just that attribute.
  """

  input_rdf_type = "RDFURN"

  def Convert(self, metadata, stat_entry, token=None):
    return self.BatchConvert([(metadata, stat_entry)], token=token)

  def BatchConvert(self, metadata_value_pairs, token=None):
    urn_metadata_pairs = []
    for metadata, value in metadata_value_pairs:
      if isinstance(value, rdfvalue.RDFURN):
        urn_metadata_pairs.append((value, metadata))

    urns_dict = dict(urn_metadata_pairs)
    fds = aff4.FACTORY.MultiOpen(urns_dict.iterkeys(), mode="r", token=token)

    batch = []
    for fd in fds:
      batch.append((urns_dict[fd.urn], fd))

    converters_classes = ExportConverter.GetConvertersByValue(
        batch[0][1])
    converters = [cls(self.options) for cls in converters_classes]
    if not converters:
      logging.info("No converters found for %s.",
                   batch[0][1].__class__.__name__)

    converted_batch = []
    for converter in converters:
      converted_batch.extend(converter.BatchConvert(batch, token=token))

    return converted_batch


class RDFValueCollectionConverter(ExportConverter):

  input_rdf_type = "RDFValueCollection"

  BATCH_SIZE = 1000

  def Convert(self, metadata, collection, token=None):
    if not collection:
      return

    converters_classes = ExportConverter.GetConvertersByValue(collection[0])
    converters = [cls(self.options) for cls in converters_classes]

    for batch in utils.Grouper(collection, self.BATCH_SIZE):
      print ["A", [str(s) for s in batch]]
      batch_with_metadata = [(metadata, v) for v in batch]
      converted_batch = []
      for converter in converters:
        converted_batch.extend(
            converter.BatchConvert(batch_with_metadata, token=token))

      for v in converted_batch:
        yield v


class VFSFileToExportedFileConverter(ExportConverter):

  input_rdf_type = "VFSFile"

  def Convert(self, metadata, vfs_file, token=None):
    stat_entry = vfs_file.Get(vfs_file.Schema.STAT)
    if not stat_entry:
      return []

    result = ExportedFile(metadata=metadata,
                          urn=stat_entry.aff4path,
                          basename=stat_entry.pathspec.Basename(),
                          st_mode=stat_entry.st_mode,
                          st_ino=stat_entry.st_ino,
                          st_dev=stat_entry.st_dev,
                          st_nlink=stat_entry.st_nlink,
                          st_uid=stat_entry.st_uid,
                          st_gid=stat_entry.st_gid,
                          st_size=stat_entry.st_size,
                          st_atime=stat_entry.st_atime,
                          st_mtime=stat_entry.st_mtime,
                          st_ctime=stat_entry.st_ctime,
                          st_blocks=stat_entry.st_blocks,
                          st_blksize=stat_entry.st_blksize,
                          st_rdev=stat_entry.st_rdev,
                          symlink=stat_entry.symlink)

    hash_obj = vfs_file.Get(vfs_file.Schema.HASH)
    if hash_obj:
      StatEntryToExportedFileConverter.ParseFileHash(hash_obj, result)

    return [result]


class GrrMessageConverter(ExportConverter):
  """Converts GrrMessage's payload into a set of RDFValues.

  GrrMessageConverter converts given GrrMessages to a set of exportable
  RDFValues. It looks at the payload of every message and applies necessary
  converters to produce the resulting RDFValues.

  Usually, when a value is converted via one of the ExportConverter classes,
  metadata (ExportedMetadata object describing the client, session id, etc)
  are provided by the caller. But when converting GrrMessages, the caller can't
  provide any reasonable metadata. In order to understand where the messages
  are coming from, one actually has to inspect the messages source and this
  is done by GrrMessageConverter and not by the caller.

  Although ExportedMetadata should still be provided for the conversion to
  happen, only "session_id" and "timestamp" values will be used. All other
  metadata will be fetched from the client object pointed to by
  GrrMessage.source.
  """

  input_rdf_type = "GrrMessage"

  def __init__(self, *args, **kw):
    super(GrrMessageConverter, self).__init__(*args, **kw)
    self.cached_metadata = {}

  def Convert(self, metadata, stat_entry, token=None):
    """Converts GrrMessage into a set of RDFValues.

    Args:
      metadata: ExporteMetadata to be used for conversion.
      stat_entry: StatEntry to be converted.
      token: Security token.

    Returns:
      List or generator with resulting RDFValues. Empty list if StatEntry
      corresponds to a registry entry and not to a file.
    """
    return self.BatchConvert([(metadata, stat_entry)], token=token)

  def BatchConvert(self, metadata_value_pairs, token=None):
    """Converts a batch of StatEntry value to ExportedFile values at once.

    Args:
      metadata_value_pairs: a list or a generator of tuples (metadata, value),
                            where metadata is ExportedMetadata to be used for
                            conversion and value is a StatEntry to be converted.
      token: Security token:

    Returns:
      Resulting RDFValues. Empty list is a valid result and means that
      conversion wasn't possible.
    """
    # Find set of converters for the first message payload.
    # We assume that payload is of the same type for all the messages in the
    # batch.
    converters_classes = ExportConverter.GetConvertersByValue(
        metadata_value_pairs[0][1].payload)
    converters = [cls(self.options) for cls in converters_classes]

    # Group messages by source (i.e. by client urn).
    msg_dict = {}
    for metadata, msg in metadata_value_pairs:
      if msg.source not in msg_dict:
        msg_dict[msg.source] = []
      msg_dict[msg.source].append((metadata, msg))

    metadata_objects = []
    metadata_to_fetch = []
    # Open the clients we don't have metadata for and fetch metadata.
    for client_urn in msg_dict.iterkeys():
      try:
        metadata_objects.append(self.cached_metadata[client_urn])
      except KeyError:
        metadata_to_fetch.append(client_urn)

    if metadata_to_fetch:
      client_fds = aff4.FACTORY.MultiOpen(metadata_to_fetch, mode="r",
                                          token=token)
      fetched_metadata = [GetMetadata(client_fd, token=token)
                          for client_fd in client_fds]
      for metadata in fetched_metadata:
        self.cached_metadata[metadata.client_urn] = metadata
      metadata_objects.extend(fetched_metadata)

    # Get session id and timestamp from the original metadata provided.
    batch_data = []
    for metadata in metadata_objects:
      try:
        for original_metadata, message in msg_dict[metadata.client_urn]:
          new_metadata = rdfvalue.ExportedMetadata(metadata)
          new_metadata.session_id = original_metadata.session_id
          new_metadata.timestamp = original_metadata.timestamp
          batch_data.append((new_metadata, message.payload))

      except KeyError:
        pass

    converted_batch = []
    for converter in converters:
      converted_batch.extend(converter.BatchConvert(batch_data, token=token))

    return converted_batch


class FileStoreImageToExportedFileStoreHashConverter(ExportConverter):
  """Converts FileStoreImage to ExportedFileStoreHash."""

  input_rdf_type = "ExportedFileStoreImage"

  def Convert(self, metadata, stat_entry, token=None):
    """Converts StatEntry to ExportedFile.

    Does nothing if StatEntry corresponds to a registry entry and not to a file.

    Args:
      metadata: ExporteMetadata to be used for conversion.
      stat_entry: StatEntry to be converted.
      token: Security token.

    Returns:
      List or generator with resulting RDFValues. Empty list if StatEntry
      corresponds to a registry entry and not to a file.
    """
    return self.BatchConvert([(metadata, stat_entry)], token=token)

  def BatchConvert(self, metadata_value_pairs, token=None):
    """Converts a batch of StatEntry value to ExportedFile values at once.

    Args:
      metadata_value_pairs: a list or a generator of tuples (metadata, value),
                            where metadata is ExportedMetadata to be used for
                            conversion and value is a StatEntry to be converted.
      token: Security token:

    Yields:
      Resulting ExportedFile values. Empty list is a valid result and means that
      conversion wasn't possible.
    """
    raise NotImplementedError()


def GetMetadata(client, token=None):
  """Builds ExportedMetadata object for a given client id.

  Args:
    client: RDFURN of a client or VFSGRRClient object itself.
    token: Security token.

  Returns:
    ExportedMetadata object with metadata of the client.
  """

  if isinstance(client, rdfvalue.RDFURN):
    client_fd = aff4.FACTORY.Open(client, mode="r", token=token)
  else:
    client_fd = client

  metadata = ExportedMetadata()

  metadata.timestamp = rdfvalue.RDFDatetime().Now()

  metadata.client_urn = client_fd.urn
  metadata.client_age = client_fd.urn.age

  metadata.hostname = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.HOSTNAME, u""))

  metadata.os = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.SYSTEM, u""))

  metadata.uname = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.UNAME, u""))

  metadata.os_release = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.OS_RELEASE, u""))

  metadata.os_version = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.OS_VERSION, u""))

  metadata.usernames = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.USERNAMES, u""))

  metadata.mac_address = utils.SmartUnicode(
      client_fd.Get(client_fd.Schema.MAC_ADDRESS, u""))

  return metadata


def ConvertSingleValue(metadata, value, token=None, options=None):
  """Finds converters for a single value and converts it."""

  converters_classes = ExportConverter.GetConvertersByValue(value)
  if not converters_classes:
    raise NoConverterFound("No converters found for value: %s" % value)

  for converter_cls in converters_classes:
    converter = converter_cls(options=options)
    for v in converter.Convert(metadata, value, token=token):
      yield v


class RDFValuesExportConverter(threadpool.BatchConverter):
  """Class used to convert sets of RDFValues to their exported versions."""

  def __init__(self, batch_size=1000, threadpool_prefix="export_converter",
               threadpool_size=10, default_metadata=None, options=None,
               token=None):
    """Constructor of RDFValueCollectionConverter.

    Args:
      batch_size: All the values will be processed in batches of this size.
      threadpool_prefix: Prefix that will be used in thread pool's threads
                         names.
      threadpool_size: Size of a thread pool that will be used.
                       If threadpool_size is 0, no threads will be used
                       and all conversions will be done in the current
                       thread.
      default_metadata: Metadata that will be used for exported values by
                        default. ExportConverters will use this metadata
                        object if they cannot collect their own metadata.
      options: ExportOptions used by the ExportConverters.
      token: Security token.
    """
    super(RDFValuesExportConverter, self).__init__(
        batch_size=batch_size, threadpool_prefix=threadpool_prefix,
        threadpool_size=threadpool_size)

    self.default_metadata = default_metadata or rdfvalue.ExportedMetadata(
        timestamp=rdfvalue.RDFDatetime().Now())
    self.options = options
    self.token = token

    self.converters = []

  def ProcessConvertedBatch(self, converted_batch):
    """Callback function that is called after every converted batch.

    It delegates handlign of the converted values to user-provided callback.

    Args:
      converted_batch: List or a generator of RDFValues.
    """
    pass

  def ConvertBatch(self, batch):
    """Converts batch of values at once."""

    if not self.converters:
      converters_classes = ExportConverter.GetConvertersByValue(batch[0])
      if not converters_classes:
        raise NoConverterFound(
            "No converters found for value: %s" % str(batch[0]))

      self.converters = [cls(self.options) for cls in converters_classes]

    batch_data = [(self.default_metadata, obj) for obj in batch]

    converted_batch = []
    for converter in self.converters:
      converted_batch.extend(
          converter.BatchConvert(batch_data, token=self.token))

    self.ProcessConvertedBatch(converted_batch)


class RDFValuesExportConverterToList(RDFValuesExportConverter):
  """RDFValueCollectionConverter that accumulates results in a list."""

  def __init__(self, *args, **kwargs):
    super(RDFValuesExportConverterToList, self).__init__(*args, **kwargs)
    self.results = []

  def ProcessConvertedBatch(self, batch):
    self.results.extend(batch)
