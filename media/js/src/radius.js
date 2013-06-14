require(['libs/jquery'], function () {
    $(document).ready(function () {
        $('#id_timestamp_0').attr('disabled', 'disabled');
        $('#id_timestamp_1').attr('disabled', 'disabled');
        $('#mode_days').change(function() {
            if ($(this).is(':checked')) {
                $('#id_timestamp_0').attr('disabled', 'disabled');
                $('#id_timestamp_1').attr('disabled', 'disabled');
                $('#id_days').removeAttr('disabled');
            }
        });

        $('#mode_timestamp').change(function() {
            if ($(this).is(':checked')) {
                $('#id_days').attr('disabled', 'disabled');
                $('#id_timestamp_0').removeAttr('disabled');
                $('#id_timestamp_1').removeAttr('disabled');
            }
        });

        $('#mode_all').change(function() {
            if ($(this).is(':checked')) {
                $('#id_days').attr('disabled', 'disabled');
                $('#id_days').val('');
                $('#id_timestamp_0').attr('disabled', 'disabled');
                $('#id_timestamp_1').attr('disabled', 'disabled');
            }
        });
    });
});
